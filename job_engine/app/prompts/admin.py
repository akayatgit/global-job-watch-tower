"""Prompt Tower admin queries — the VIGIL cockpit reads these, never jobs.

Numbers are computed from stored rows. The model never authors a count,
score, or source. Same law as the job boards: the tower is the truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app import config
from app.models import ConsoleLog, PromptRender, VideoPrompt
from app.prompts import pipeline


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def window_start(days: int, *, now: datetime | None = None) -> datetime:
    """0 = rolling 24h · 1 = local calendar today · N = last N days."""
    now = now or utcnow()
    if days <= 0:
        return now - timedelta(hours=24)
    if days == 1:
        local = datetime.now().astimezone()
        return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    return now - timedelta(days=days)


def next_pipeline_at(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    hour = int(getattr(config, 'PROMPT_PIPELINE_UTC_HOUR', 3) or 3)
    minute = int(getattr(config, 'PROMPT_PIPELINE_UTC_MINUTE', 30) or 30)
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= now:
        when = when + timedelta(days=1)
    return when


def _csv(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or '').split(',') if part.strip()]


def list_prompts(
    db: Session,
    *,
    q: str = '',
    source: str = '',
    category: str = '',
    status: str = '',
    days: int | None = None,
    sort: str = 'newest',
    limit: int = 80,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(VideoPrompt)
    if q:
        needle = f'%{q.strip()}%'
        stmt = stmt.where(or_(
            VideoPrompt.title.ilike(needle),
            VideoPrompt.text.ilike(needle),
            VideoPrompt.author.ilike(needle),
        ))
    if source:
        stmt = stmt.where(VideoPrompt.source == source)
    if category:
        stmt = stmt.where(VideoPrompt.category == category)
    if status:
        stmt = stmt.where(VideoPrompt.status == status)
    if days is not None:
        stmt = stmt.where(VideoPrompt.collected_at >= window_start(days))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if sort == 'score':
        stmt = stmt.order_by(desc(VideoPrompt.final_score), desc(VideoPrompt.id))
    elif sort == 'rating':
        stmt = stmt.order_by(desc(VideoPrompt.rating), desc(VideoPrompt.id))
    else:
        stmt = stmt.order_by(desc(VideoPrompt.collected_at), desc(VideoPrompt.id))

    rows = db.execute(stmt.offset(max(0, offset)).limit(max(1, min(limit, 200)))).scalars().all()
    return {
        'total': int(total),
        'shown': len(rows),
        'offset': max(0, offset),
        'sort': sort if sort in ('newest', 'score', 'rating') else 'newest',
        'prompts': [pipeline.serialize_prompt(row) for row in rows],
    }


def insights(db: Session, *, days: int = 7) -> dict[str, Any]:
    now = utcnow()
    since = window_start(days, now=now)
    today = window_start(1, now=now)
    since_24h = window_start(0, now=now)

    def _count(extra=None, start=None):
        stmt = select(func.count(VideoPrompt.id))
        if start is not None:
            stmt = stmt.where(VideoPrompt.collected_at >= start)
        if extra is not None:
            stmt = stmt.where(extra)
        return int(db.scalar(stmt) or 0)

    top_sources = [
        {'id': source or 'unknown', 'label': (source or 'unknown').title(), 'n': int(n)}
        for source, n in db.execute(
            select(VideoPrompt.source, func.count(VideoPrompt.id))
            .where(VideoPrompt.collected_at >= since)
            .group_by(VideoPrompt.source)
            .order_by(desc(func.count(VideoPrompt.id)))
        ).all()
    ]
    by_category = [
        {'id': category or 'other', 'label': (category or 'other').title(), 'n': int(n)}
        for category, n in db.execute(
            select(VideoPrompt.category, func.count(VideoPrompt.id))
            .where(VideoPrompt.collected_at >= since)
            .group_by(VideoPrompt.category)
            .order_by(desc(func.count(VideoPrompt.id)))
        ).all()
    ]
    shortlist = [
        pipeline.serialize_prompt(prompt, rank=entry.rank)
        for entry, prompt in pipeline.shortlist_for_day(db, now.date())
    ]
    latest = [
        pipeline.serialize_prompt(row)
        for row in db.execute(
            select(VideoPrompt).order_by(desc(VideoPrompt.collected_at)).limit(10)
        ).scalars().all()
    ]
    sources_opt = [{'id': '', 'label': 'All sources'}] + [
        {'id': row['id'], 'label': row['label']} for row in top_sources
    ]
    category_opt = [{'id': '', 'label': 'All categories'}] + [
        {'id': row['id'], 'label': row['label']} for row in by_category if row['id'] != 'other' or row['n']
    ]
    return {
        'days': days,
        'stats': {
            'total': _count(),
            'today': _count(start=today),
            'last_24h': _count(start=since_24h),
            'scored': _count(VideoPrompt.scored_at.is_not(None)),
            'pending_score': _count(VideoPrompt.scored_at.is_(None)),
            'shortlisted_today': len(shortlist),
            'outliers': _count(VideoPrompt.is_outlier.is_(True)),
            'exemplars': _count(VideoPrompt.exemplar.is_(True)),
            'posted': _count(VideoPrompt.status == 'posted'),
            'renders_done': int(db.scalar(
                select(func.count(PromptRender.id)).where(PromptRender.status == 'done')
            ) or 0),
        },
        'top_sources': top_sources,
        'by_category': by_category,
        'shortlist': shortlist,
        'latest': latest,
        'source_options': sources_opt,
        'category_options': category_opt,
        'next_scan_at': next_pipeline_at(now).isoformat(),
    }


def signals(db: Session, *, days: int = 7) -> dict[str, Any]:
    now = utcnow()
    since = window_start(days, now=now)
    prior_start = since - (now - since)

    recent = db.execute(
        select(VideoPrompt).where(VideoPrompt.collected_at >= since)
    ).scalars().all()
    prior = db.execute(
        select(VideoPrompt).where(
            VideoPrompt.collected_at >= prior_start,
            VideoPrompt.collected_at < since,
        )
    ).scalars().all()

    def _by(rows: list[VideoPrompt], key) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows:
            name = getattr(row, key) or 'other'
            out[name] = out.get(name, 0) + 1
        return out

    recent_cat = _by(recent, 'category')
    prior_cat = _by(prior, 'category')
    growing = []
    for name, count in recent_cat.items():
        delta = count - prior_cat.get(name, 0)
        growing.append({'id': name, 'label': name.title(), 'n': count, 'delta': delta})
    growing.sort(key=lambda row: (row['delta'], row['n']), reverse=True)

    recent_src = _by(recent, 'source')
    prior_src = _by(prior, 'source')
    fastest = []
    for name, count in recent_src.items():
        delta = count - prior_src.get(name, 0)
        fastest.append({'id': name, 'label': name.title(), 'n': count, 'delta': delta})
    fastest.sort(key=lambda row: (row['delta'], row['n']), reverse=True)

    scored = [row.final_score for row in recent if row.final_score is not None]
    bands = [
        {'id': '90+', 'label': '90–100', 'n': sum(1 for s in scored if s >= 90)},
        {'id': '75', 'label': '75–89', 'n': sum(1 for s in scored if 75 <= s < 90)},
        {'id': '55', 'label': '55–74', 'n': sum(1 for s in scored if 55 <= s < 75)},
        {'id': 'low', 'label': 'Under 55', 'n': sum(1 for s in scored if s < 55)},
    ]
    return {
        'days': days,
        'window_options': [
            {'days': 0, 'label': 'Last 24 hours'},
            {'days': 1, 'label': 'Today'},
            {'days': 2, 'label': 'Last 2 days'},
            {'days': 7, 'label': 'Last 7 days'},
            {'days': 14, 'label': 'Last 14 days'},
            {'days': 30, 'label': 'Last 30 days'},
        ],
        'signals': {
            'recent_total': len(recent),
            'scored': len(scored),
            'outliers': sum(1 for row in recent if row.is_outlier),
            'mean_score': round(sum(scored) / len(scored), 1) if scored else None,
            'growing_categories': growing[:12],
            'fastest_sources': fastest[:12],
            'score_bands': bands,
        },
        'source_options': [{'id': '', 'label': 'All sources'}] + [
            {'id': row['id'], 'label': row['label']} for row in fastest
        ],
        'category_options': [{'id': '', 'label': 'All categories'}] + [
            {'id': row['id'], 'label': row['label']} for row in growing if row['id'] != 'other'
        ],
    }


def activity(db: Session, *, limit: int = 40) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    prompts = db.execute(
        select(VideoPrompt).order_by(desc(VideoPrompt.collected_at)).limit(limit)
    ).scalars().all()
    for row in prompts:
        events.append({
            'id': f'catch-{row.id}',
            'kind': 'caught',
            'status': row.status,
            'title': row.title or f'Prompt #{row.id}',
            'meta': f'{row.source or "—"} · score {row.final_score if row.final_score is not None else "pending"}',
            'at': row.collected_at.isoformat() if row.collected_at else None,
            'prompt_id': row.id,
        })
        if row.scored_at:
            events.append({
                'id': f'score-{row.id}',
                'kind': 'scored',
                'status': 'scored',
                'title': row.title or f'Prompt #{row.id}',
                'meta': f'Hermes {row.ai_score} · blend {row.final_score}',
                'at': row.scored_at.isoformat(),
                'prompt_id': row.id,
            })
    renders = db.execute(
        select(PromptRender).order_by(desc(PromptRender.requested_at)).limit(limit)
    ).scalars().all()
    for row in renders:
        events.append({
            'id': f'render-{row.id}',
            'kind': 'render',
            'status': row.status,
            'title': f'Video #{row.id}',
            'meta': row.error or row.model or 'queued',
            'at': (row.finished_at or row.requested_at).isoformat() if (row.finished_at or row.requested_at) else None,
            'prompt_id': row.prompt_id,
        })
    logs = db.execute(
        select(ConsoleLog)
        .where(or_(
            ConsoleLog.message.ilike('%prompt%'),
            ConsoleLog.source.in_(('beat', 'worker')),
        ))
        .order_by(desc(ConsoleLog.id))
        .limit(limit)
    ).scalars().all()
    for row in logs:
        msg = row.message or ''
        if 'prompt' not in msg.lower() and 'Prompt Tower' not in msg:
            continue
        events.append({
            'id': f'log-{row.id}',
            'kind': row.source or 'log',
            'status': row.level or 'info',
            'title': msg[:160],
            'meta': row.source or 'log',
            'at': row.ts.isoformat() if row.ts else None,
            'prompt_id': None,
        })
    events.sort(key=lambda item: item.get('at') or '', reverse=True)
    return {'total': len(events), 'events': events[:limit]}


def sources(db: Session) -> dict[str, Any]:
    counts = {
        source: int(n) for source, n in db.execute(
            select(VideoPrompt.source, func.count(VideoPrompt.id)).group_by(VideoPrompt.source)
        ).all()
    }
    last = {
        source: ts.isoformat() if ts else None
        for source, ts in db.execute(
            select(VideoPrompt.source, func.max(VideoPrompt.collected_at)).group_by(VideoPrompt.source)
        ).all()
    }
    reddit_names = _csv(getattr(config, 'PROMPT_REDDIT_SUBS', ''))
    reddit = [
        {
            'id': f'reddit:{name}',
            'kind': 'reddit',
            'name': f'r/{name}',
            'enabled': True,
            'caught': counts.get('reddit', 0) if i == 0 else None,
            'last_at': last.get('reddit'),
        }
        for i, name in enumerate(reddit_names)
    ]
    if not reddit:
        reddit = [{
            'id': 'reddit',
            'kind': 'reddit',
            'name': 'Reddit',
            'enabled': False,
            'caught': counts.get('reddit', 0),
            'last_at': last.get('reddit'),
        }]

    web_urls = _csv(getattr(config, 'PROMPT_WEB_URLS', ''))
    web = [
        {
            'id': f'web:{i}',
            'kind': 'web',
            'name': url,
            'enabled': True,
            'caught': counts.get('web', 0) if i == 0 else None,
            'last_at': last.get('web'),
        }
        for i, url in enumerate(web_urls)
    ]
    if not web:
        web = [{
            'id': 'web',
            'kind': 'web',
            'name': 'Web pages (none configured)',
            'enabled': False,
            'caught': counts.get('web', 0),
            'last_at': last.get('web'),
        }]

    ig_tags = _csv(getattr(config, 'PROMPT_INSTAGRAM_TAGS', ''))
    instagram = [
        {
            'id': f'instagram:{tag}',
            'kind': 'instagram',
            'name': f'#{tag}',
            'enabled': True,
            'caught': counts.get('instagram', 0) if i == 0 else None,
            'last_at': last.get('instagram'),
        }
        for i, tag in enumerate(ig_tags)
    ]
    if not instagram:
        instagram = [{
            'id': 'instagram',
            'kind': 'instagram',
            'name': 'Instagram hashtags (off)',
            'enabled': False,
            'caught': counts.get('instagram', 0),
            'last_at': last.get('instagram'),
        }]

    manual = [{
        'id': 'manual',
        'kind': 'manual',
        'name': 'Pasted by you',
        'enabled': True,
        'caught': counts.get('manual', 0),
        'last_at': last.get('manual'),
    }]
    families = reddit + web + instagram + manual
    return {
        'total_caught': sum(counts.values()),
        'sources': families,
        'by_family': [
            {'id': name, 'label': name.title(), 'n': counts.get(name, 0), 'last_at': last.get(name)}
            for name in ('reddit', 'web', 'instagram', 'manual')
        ],
        'next_scan_at': next_pipeline_at().isoformat(),
    }


def winners(db: Session) -> dict[str, Any]:
    exemplars = db.execute(
        select(VideoPrompt)
        .where(VideoPrompt.exemplar.is_(True))
        .order_by(desc(VideoPrompt.performance_score), desc(VideoPrompt.rating))
        .limit(20)
    ).scalars().all()
    posted = db.execute(
        select(VideoPrompt)
        .where(VideoPrompt.status == 'posted')
        .order_by(desc(VideoPrompt.posted_at))
        .limit(20)
    ).scalars().all()
    rated = db.execute(
        select(VideoPrompt)
        .where(VideoPrompt.rating.is_not(None))
        .order_by(desc(VideoPrompt.rating), desc(VideoPrompt.id))
        .limit(20)
    ).scalars().all()
    return {
        'exemplars': [pipeline.serialize_prompt(row) for row in exemplars],
        'posted': [pipeline.serialize_prompt(row) for row in posted],
        'rated': [pipeline.serialize_prompt(row) for row in rated],
    }


def mix(db: Session, *, days: int = 7) -> dict[str, Any]:
    since = window_start(days)
    rows = db.execute(
        select(VideoPrompt).where(
            VideoPrompt.collected_at >= since,
            VideoPrompt.scored_at.is_not(None),
        )
    ).scalars().all()
    heuristic = [row.heuristic_score for row in rows if row.heuristic_score is not None]
    ai = [row.ai_score for row in rows if row.ai_score is not None]
    blended = [row.final_score for row in rows if row.final_score is not None]
    outliers = sum(1 for row in rows if row.is_outlier)

    def _mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    return {
        'days': days,
        'window_options': [
            {'days': 0, 'label': 'Last 24 hours'},
            {'days': 1, 'label': 'Today'},
            {'days': 7, 'label': 'Last 7 days'},
            {'days': 30, 'label': 'Last 30 days'},
        ],
        'heuristic_n': len(heuristic),
        'ai_n': len(ai),
        'blended_n': len(blended),
        'heuristic_mean': _mean(heuristic),
        'ai_mean': _mean(ai),
        'blended_mean': _mean(blended),
        'outliers': outliers,
        'items': [
            {'id': 'recipe', 'label': 'Recipe', 'value': _mean(heuristic) or 0},
            {'id': 'hermes', 'label': 'Hermes', 'value': _mean(ai) or 0},
            {'id': 'blend', 'label': 'Blend', 'value': _mean(blended) or 0},
        ],
    }


def categories(db: Session, *, days: int = 7) -> dict[str, Any]:
    since = window_start(days)
    rows = [
        {
            'id': category or 'other',
            'label': (category or 'other').title(),
            'n': int(n),
        }
        for category, n in db.execute(
            select(VideoPrompt.category, func.count(VideoPrompt.id))
            .where(VideoPrompt.collected_at >= since)
            .group_by(VideoPrompt.category)
            .order_by(desc(func.count(VideoPrompt.id)))
        ).all()
    ]
    return {
        'days': days,
        'window_options': [
            {'days': 0, 'label': 'Last 24 hours'},
            {'days': 1, 'label': 'Today'},
            {'days': 7, 'label': 'Last 7 days'},
            {'days': 14, 'label': 'Last 14 days'},
            {'days': 30, 'label': 'Last 30 days'},
        ],
        'categories': rows,
        'total': sum(row['n'] for row in rows),
    }


def pulse(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Header / Health numbers when the job beat is asleep."""
    now = now or utcnow()
    today = window_start(1, now=now)
    since_24h = window_start(0, now=now)
    collected_today = int(db.scalar(
        select(func.count(VideoPrompt.id)).where(VideoPrompt.collected_at >= today)
    ) or 0)
    collected_24h = int(db.scalar(
        select(func.count(VideoPrompt.id)).where(VideoPrompt.collected_at >= since_24h)
    ) or 0)
    pending = int(db.scalar(
        select(func.count(VideoPrompt.id)).where(VideoPrompt.scored_at.is_(None))
    ) or 0)
    last = db.scalar(select(func.max(VideoPrompt.collected_at)))
    next_at = next_pipeline_at(now)
    running = False
    recent = db.execute(
        select(ConsoleLog)
        .where(
            ConsoleLog.ts >= now - timedelta(minutes=8),
            ConsoleLog.message.ilike('%Prompt Tower%'),
        )
        .order_by(desc(ConsoleLog.id))
        .limit(1)
    ).scalar_one_or_none()
    if recent is not None:
        msg = (recent.message or '').lower()
        running = 'started' in msg or 'scoring' in msg

    stalled = False
    stall_detail = ''
    last_aware = _aware(last)
    scheduled_today = now.replace(
        hour=int(getattr(config, 'PROMPT_PIPELINE_UTC_HOUR', 3) or 3),
        minute=int(getattr(config, 'PROMPT_PIPELINE_UTC_MINUTE', 30) or 30),
        second=0,
        microsecond=0,
    )
    if last_aware is not None and now > scheduled_today + timedelta(hours=2):
        idle = now - last_aware
        if idle > timedelta(hours=26):
            stalled = True
            stall_detail = (
                f'No new prompts collected for {int(idle.total_seconds() // 3600)}h — '
                'daily scan looks stuck. Open Sources and tap Scan now.'
            )
    return {
        'collected_today': collected_today,
        'collected_24h': collected_24h,
        'pending_score': pending,
        'last_collected_at': last,
        'next_at': next_at,
        'next_secs': max(0, int((next_at - now).total_seconds())),
        'running': running,
        'stalled': stalled,
        'stall_detail': stall_detail,
    }
