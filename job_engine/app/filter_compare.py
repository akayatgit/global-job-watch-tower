"""AI (Ollama) vs Keyword (Plan B) filter comparison for VIGIL."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import TowerEvent

IST = ZoneInfo('Asia/Kolkata')

# (key, short chip label, human label)
FILTER_WINDOWS: list[tuple[str, str, str]] = [
    ('1h', '1h', 'Last 1 hour'),
    ('5h', '5h', 'Last 5 hours'),
    ('12h', '12h', 'Last 12 hours'),
    ('24h', '24h', 'Last 24 hours'),
    ('1d', '1 day', 'Today'),
    ('2d', '2d', 'Last 2 days'),
    ('5d', '5d', 'Last 5 days'),
    ('1w', '1 week', 'Last 7 days'),
    ('last_week', 'Last week', 'Previous calendar week'),
    ('this_month', 'This month', 'This calendar month'),
    ('last_month', 'Last month', 'Previous calendar month'),
]

ALLOWED_FILTER_WINDOWS = {k for k, _, _ in FILTER_WINDOWS}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_ist() -> datetime:
    return datetime.now(IST)


def window_bounds(key: str) -> tuple[datetime, datetime, str]:
    """Return (start_utc, end_utc, bucket) where bucket is 'hour' or 'day'."""
    key = (key or '24h').strip().lower()
    if key not in ALLOWED_FILTER_WINDOWS:
        key = '24h'

    now_u = _now_utc()
    now_i = _now_ist()

    if key == '1h':
        return now_u - timedelta(hours=1), now_u, 'hour'
    if key == '5h':
        return now_u - timedelta(hours=5), now_u, 'hour'
    if key == '12h':
        return now_u - timedelta(hours=12), now_u, 'hour'
    if key == '24h':
        return now_u - timedelta(hours=24), now_u, 'hour'
    if key == '1d':
        start_i = now_i.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_i.astimezone(timezone.utc), now_u, 'hour'
    if key == '2d':
        start_i = (now_i - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_i.astimezone(timezone.utc), now_u, 'day'
    if key == '5d':
        start_i = (now_i - timedelta(days=4)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_i.astimezone(timezone.utc), now_u, 'day'
    if key == '1w':
        start_i = (now_i - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_i.astimezone(timezone.utc), now_u, 'day'
    if key == 'last_week':
        # Previous Mon 00:00 IST → this Mon 00:00 IST
        today = now_i.date()
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        start_i = datetime(last_monday.year, last_monday.month, last_monday.day, tzinfo=IST)
        end_i = datetime(this_monday.year, this_monday.month, this_monday.day, tzinfo=IST)
        return start_i.astimezone(timezone.utc), end_i.astimezone(timezone.utc), 'day'
    if key == 'this_month':
        start_i = now_i.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start_i.astimezone(timezone.utc), now_u, 'day'
    if key == 'last_month':
        first_this = now_i.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_last = first_this - timedelta(seconds=1)
        start_i = last_month_last.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_i = first_this
        return start_i.astimezone(timezone.utc), end_i.astimezone(timezone.utc), 'day'

    return now_u - timedelta(hours=24), now_u, 'hour'


def compute_filter_compare(db: Session, window: str = '24h') -> dict:
    start, end, bucket = window_bounds(window)
    label = next((lab for k, _, lab in FILTER_WINDOWS if k == window), 'Last 24 hours')
    chip = next((c for k, c, _ in FILTER_WINDOWS if k == window), '24h')

    ai_n = db.execute(
        select(func.count(TowerEvent.id)).where(
            TowerEvent.kind == 'ollama_filter',
            TowerEvent.ts >= start,
            TowerEvent.ts < end,
        )
    ).scalar() or 0
    kw_n = db.execute(
        select(func.count(TowerEvent.id)).where(
            TowerEvent.kind == 'keyword_filter',
            TowerEvent.ts >= start,
            TowerEvent.ts < end,
        )
    ).scalar() or 0
    total = ai_n + kw_n
    ai_pct = round((ai_n / total) * 100, 1) if total else 0.0
    kw_pct = round((kw_n / total) * 100, 1) if total else 0.0

    # Timeline buckets
    if bucket == 'hour':
        trunc = func.date_trunc('hour', TowerEvent.ts)
    else:
        trunc = func.date_trunc('day', TowerEvent.ts)

    bucket_col = trunc.label('bucket')
    rows = db.execute(
        select(
            bucket_col,
            func.sum(case((TowerEvent.kind == 'ollama_filter', 1), else_=0)).label('ai'),
            func.sum(case((TowerEvent.kind == 'keyword_filter', 1), else_=0)).label('keyword'),
        )
        .where(
            TowerEvent.kind.in_(('ollama_filter', 'keyword_filter')),
            TowerEvent.ts >= start,
            TowerEvent.ts < end,
        )
        .group_by(bucket_col)
        .order_by(bucket_col)
    ).all()

    series = []
    for b, ai, kw in rows:
        if b is None:
            continue
        ts = b
        if getattr(ts, 'tzinfo', None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        series.append({
            'at': ts.astimezone(IST).isoformat(),
            'label': ts.astimezone(IST).strftime('%d %b %H:%M' if bucket == 'hour' else '%d %b'),
            'ai': int(ai or 0),
            'keyword': int(kw or 0),
        })

    max_bar = max([ai_n, kw_n, 1])
    series_max = max([max(s['ai'], s['keyword']) for s in series] + [1])

    if total == 0:
        headline = f'No filter runs in {label.lower()}.'
    elif ai_n >= kw_n:
        headline = (
            f'AI led this window — {ai_n} Ollama vs {kw_n} Plan B keyword '
            f'({ai_pct}% AI).'
        )
    else:
        headline = (
            f'Plan B was heavier — {kw_n} keyword vs {ai_n} Ollama '
            f'({kw_pct}% keyword). Heat pacing aims to flip this toward AI.'
        )

    return {
        'window': window if window in ALLOWED_FILTER_WINDOWS else '24h',
        'chip': chip,
        'label': label,
        'bucket': bucket,
        'start': start.astimezone(IST).isoformat(),
        'end': end.astimezone(IST).isoformat(),
        'ai': ai_n,
        'keyword': kw_n,
        'total': total,
        'ai_pct': ai_pct,
        'keyword_pct': kw_pct,
        'max_bar': max_bar,
        'series_max': series_max,
        'series': series,
        'headline': headline,
        'window_options': [
            {'key': k, 'chip': c, 'label': lab} for k, c, lab in FILTER_WINDOWS
        ],
    }
