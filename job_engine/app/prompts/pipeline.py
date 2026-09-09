"""Daily Prompt Tower pipeline: collect → dedupe → score → top-10.

Pure functions over a SQLAlchemy session so the Celery task, the API and
the tests all run the exact same code. Network (sources) and the model
(scoring) are injectable.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PromptShortlist, VideoPrompt
from app.prompts import rag, scoring
from app.prompts.normalize import read_prompt
from app.prompts.sources import Candidate, gather_candidates

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- ingest

def ingest(db: Session, candidate: Candidate) -> tuple[VideoPrompt | None, str]:
    """Store one candidate. Returns (row, outcome) where outcome is
    created | duplicate | near_duplicate | rejected."""
    reading = read_prompt(candidate.text)
    if not reading.is_prompt:
        return None, 'rejected'
    existing = db.execute(
        select(VideoPrompt).where(VideoPrompt.fingerprint == reading.fingerprint)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, 'duplicate'
    vector = rag.embed(reading.text)
    near = rag.find_duplicate(db, vector)
    if near is not None:
        return near, 'near_duplicate'
    row = VideoPrompt(
        fingerprint=reading.fingerprint,
        text=reading.text,
        title=(candidate.title or reading.title)[:300],
        source=candidate.source,
        source_url=(candidate.source_url or None),
        author=(candidate.author or None),
        source_posted_at=candidate.posted_at,
        collected_at=utcnow(),
        model_hint=reading.model_hint,
        category=reading.category,
        heuristic_score=reading.heuristic_score,
        embedding=vector,
        status='new',
    )
    db.add(row)
    db.flush()
    return row, 'created'


def ingest_many(db: Session, candidates: list[Candidate]) -> dict[str, int]:
    counts = {'created': 0, 'duplicate': 0, 'near_duplicate': 0, 'rejected': 0}
    for candidate in candidates:
        _row, outcome = ingest(db, candidate)
        counts[outcome] = counts.get(outcome, 0) + 1
    db.commit()
    return counts


# ----------------------------------------------------------------- score

def score_prompt(db: Session, prompt: VideoPrompt, *, chat: Callable[[str], str] | None = None) -> VideoPrompt:
    """Hermes grades one prompt against the nearest proven winners; the
    blend and the outlier flag are deterministic."""
    anchors = [
        (row.text, float(row.final_score or 0.0))
        for row in rag.exemplars(db, prompt.embedding)
    ]
    verdict = scoring.ai_score(prompt.text, anchors, chat=chat)
    heuristic = float(prompt.heuristic_score or read_prompt(prompt.text).heuristic_score)
    if verdict is not None:
        prompt.ai_detail = verdict.detail
        prompt.ai_flow = verdict.flow
        prompt.ai_score = verdict.score
        prompt.ai_reasons = verdict.reasons
    prompt.heuristic_score = heuristic
    prompt.final_score = scoring.blend(heuristic, verdict)
    base = rag.baseline(db)
    prompt.baseline_mean = base.mean
    prompt.baseline_std = base.std
    prompt.is_outlier = base.is_outlier(prompt.final_score)
    prompt.scored_at = utcnow()
    return prompt


def score_pending(db: Session, *, limit: int = 60, chat: Callable[[str], str] | None = None) -> int:
    rows = db.execute(
        select(VideoPrompt)
        .where(VideoPrompt.scored_at.is_(None))
        .order_by(VideoPrompt.heuristic_score.desc().nullslast(), VideoPrompt.id.asc())
        .limit(limit)
    ).scalars().all()
    for row in rows:
        try:
            score_prompt(db, row, chat=chat)
        except Exception:
            logger.exception('scoring failed for prompt %s', row.id)
        db.commit()
    return len(rows)


# ------------------------------------------------------------- shortlist

def shortlist_for_day(db: Session, day: date) -> list[tuple[PromptShortlist, VideoPrompt]]:
    rows = db.execute(
        select(PromptShortlist, VideoPrompt)
        .join(VideoPrompt, VideoPrompt.id == PromptShortlist.prompt_id)
        .where(PromptShortlist.day == day)
        .order_by(PromptShortlist.rank.asc())
    ).all()
    return [(entry, prompt) for entry, prompt in rows]


def build_shortlist(
    db: Session,
    day: date,
    *,
    size: int | None = None,
    min_score: float | None = None,
    window_hours: int = 48,
    force: bool = False,
) -> list[tuple[PromptShortlist, VideoPrompt]]:
    """Top-N scored prompts for `day`. Idempotent: an existing shortlist is
    returned as-is unless force=True (then rebuilt from current scores)."""
    from app import config

    size = size or int(getattr(config, 'PROMPT_SHORTLIST_SIZE', 10))
    min_score = float(getattr(config, 'PROMPT_MIN_SCORE', 55.0)) if min_score is None else min_score
    existing = shortlist_for_day(db, day)
    if existing and not force:
        return existing
    for entry, prompt in existing:
        if prompt.status == 'shortlisted':
            prompt.status = 'new'
        db.delete(entry)
    db.flush()

    since = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) - timedelta(hours=window_hours)
    candidates = db.execute(
        select(VideoPrompt)
        .where(
            VideoPrompt.scored_at.is_not(None),
            VideoPrompt.final_score.is_not(None),
            VideoPrompt.final_score >= min_score,
            VideoPrompt.status.in_(('new', 'shortlisted')),
            VideoPrompt.collected_at >= since,
        )
    ).scalars().all()
    # Outliers first (they beat the proven baseline), then raw score;
    # at most 3 per source so one subreddit cannot own the day.
    candidates.sort(key=lambda p: (not p.is_outlier, -(p.final_score or 0.0), p.id))
    per_source: dict[str, int] = {}
    chosen: list[VideoPrompt] = []
    for prompt in candidates:
        if per_source.get(prompt.source, 0) >= 3 and prompt.source != 'manual':
            continue
        per_source[prompt.source] = per_source.get(prompt.source, 0) + 1
        chosen.append(prompt)
        if len(chosen) >= size:
            break
    out: list[tuple[PromptShortlist, VideoPrompt]] = []
    for rank, prompt in enumerate(chosen, 1):
        entry = PromptShortlist(day=day, rank=rank, prompt_id=prompt.id, created_at=utcnow())
        prompt.status = 'shortlisted'
        db.add(entry)
        out.append((entry, prompt))
    db.commit()
    return out


# -------------------------------------------------------------- feedback

def record_rating(db: Session, prompt: VideoPrompt, rating: int) -> VideoPrompt:
    prompt.rating = max(1, min(5, int(rating)))
    prompt.performance_score = rag.performance_score(prompt.rating, prompt.performance)
    rag.promote_winners(db)
    return prompt


def record_performance(db: Session, prompt: VideoPrompt, metrics: dict[str, Any]) -> VideoPrompt:
    allowed = ('likes', 'comments', 'saves', 'shares', 'views')
    current = dict(prompt.performance or {})
    for key in allowed:
        if key in metrics and metrics[key] is not None:
            current[key] = max(0, int(metrics[key]))
    prompt.performance = current
    if not prompt.posted_at:
        prompt.posted_at = utcnow()
    if prompt.status != 'posted':
        prompt.status = 'posted'
    prompt.performance_score = rag.performance_score(prompt.rating, prompt.performance)
    rag.promote_winners(db)
    return prompt


def mark_posted(db: Session, prompt: VideoPrompt) -> VideoPrompt:
    prompt.status = 'posted'
    prompt.posted_at = prompt.posted_at or utcnow()
    return prompt


# ------------------------------------------------------------- serialize

def serialize_prompt(prompt: VideoPrompt, *, rank: int | None = None, full: bool = False) -> dict[str, Any]:
    text = prompt.text or ''
    return {
        'id': prompt.id,
        'rank': rank,
        'title': prompt.title,
        'text': text if full else text[:280],
        'text_chars': len(text),
        'source': prompt.source,
        'source_url': prompt.source_url,
        'author': prompt.author,
        'model_hint': prompt.model_hint,
        'category': prompt.category,
        'heuristic_score': prompt.heuristic_score,
        'ai_detail': prompt.ai_detail,
        'ai_flow': prompt.ai_flow,
        'ai_score': prompt.ai_score,
        'ai_reasons': prompt.ai_reasons or [],
        'final_score': prompt.final_score,
        'is_outlier': bool(prompt.is_outlier),
        'baseline_mean': prompt.baseline_mean,
        'status': prompt.status,
        'rating': prompt.rating,
        'performance': prompt.performance or {},
        'performance_score': prompt.performance_score,
        'exemplar': bool(prompt.exemplar),
        'collected_at': prompt.collected_at.isoformat() if prompt.collected_at else None,
        'scored_at': prompt.scored_at.isoformat() if prompt.scored_at else None,
        'posted_at': prompt.posted_at.isoformat() if prompt.posted_at else None,
    }


# ----------------------------------------------------------------- daily

def run_daily(
    db: Session,
    *,
    day: date | None = None,
    candidates: list[Candidate] | None = None,
    chat: Callable[[str], str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """The whole day in one call. `candidates` overrides live sources
    (tests / manual re-runs); `chat` overrides the model."""
    day = day or utcnow().date()
    if candidates is None:
        candidates = gather_candidates()
    counts = ingest_many(db, candidates)
    scored = score_pending(db, chat=chat)
    promoted = rag.promote_winners(db)
    db.commit()
    shortlist = build_shortlist(db, day, force=force)
    return {
        'day': day.isoformat(),
        'candidates': len(candidates),
        **counts,
        'scored': scored,
        'promoted': promoted,
        'shortlisted': len(shortlist),
        'top': [serialize_prompt(prompt, rank=entry.rank) for entry, prompt in shortlist],
    }
