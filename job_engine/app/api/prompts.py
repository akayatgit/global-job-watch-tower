"""Prompt Tower API — /api/prompts/* (owner surface, local tower).

The Telegram bot never touches Postgres; everything it shows Ashok and
every action he taps comes through here. Same law as jobs: rows verbatim,
numbers computed, nothing authored by a model on the way out.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date, datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PromptRender, VideoPrompt
from app.prompts import admin as prompt_admin
from app.prompts import pipeline, rag, reel_engines, video_creator
from app.prompts.sources import manual_candidate

router = APIRouter(prefix='/api/prompts')

MAX_IMAGE_BYTES = 12 * 1024 * 1024


def _parse_day(raw: str | None) -> date:
    if not raw:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(422, 'day must be YYYY-MM-DD') from exc


def _get_prompt(db: Session, prompt_id: int) -> VideoPrompt:
    row = db.get(VideoPrompt, int(prompt_id))
    if row is None:
        raise HTTPException(404, 'prompt not found')
    return row


# ---------------------------------------------------------------- reads

@router.get('/today')
def today(day: str | None = Query(default=None), full: int = Query(default=0), db: Session = Depends(get_db)):
    """The day's top-10 with rank; full=1 returns the whole prompt text."""
    when = _parse_day(day)
    rows = pipeline.shortlist_for_day(db, when)
    return {
        'day': when.isoformat(),
        'total': len(rows),
        'prompts': [pipeline.serialize_prompt(p, rank=e.rank, full=bool(full)) for e, p in rows],
    }


@router.get('')
@router.get('/')
def catalog(
    q: str = Query(default=''),
    source: str = Query(default=''),
    category: str = Query(default=''),
    status: str = Query(default=''),
    days: int | None = Query(default=None),
    sort: str = Query(default='newest'),
    limit: int = Query(default=80),
    offset: int = Query(default=0),
    db: Session = Depends(get_db),
):
    """Prompt catalogue for the VIGIL admin list — live filters, newest first."""
    return prompt_admin.list_prompts(
        db, q=q, source=source, category=category, status=status,
        days=days, sort=sort, limit=limit, offset=offset,
    )


@router.get('/insights')
def insights(days: int = Query(default=7), db: Session = Depends(get_db)):
    return prompt_admin.insights(db, days=days)


@router.get('/signals')
def signals(days: int = Query(default=7), db: Session = Depends(get_db)):
    return prompt_admin.signals(db, days=days)


@router.get('/activity')
def activity(limit: int = Query(default=40), db: Session = Depends(get_db)):
    return prompt_admin.activity(db, limit=limit)


@router.get('/sources')
def sources(db: Session = Depends(get_db)):
    return prompt_admin.sources(db)


@router.get('/winners')
def winners(db: Session = Depends(get_db)):
    return prompt_admin.winners(db)


@router.get('/mix')
def mix(days: int = Query(default=7), db: Session = Depends(get_db)):
    return prompt_admin.mix(db, days=days)


@router.get('/categories')
def categories(days: int = Query(default=7), db: Session = Depends(get_db)):
    return prompt_admin.categories(db, days=days)


@router.get('/stats')
def stats(db: Session = Depends(get_db)):
    today_day = datetime.now(timezone.utc).date()
    total = db.scalar(select(func.count(VideoPrompt.id))) or 0
    scored = db.scalar(select(func.count(VideoPrompt.id)).where(VideoPrompt.scored_at.is_not(None))) or 0
    posted = db.scalar(select(func.count(VideoPrompt.id)).where(VideoPrompt.status == 'posted')) or 0
    exemplars = db.scalar(select(func.count(VideoPrompt.id)).where(VideoPrompt.exemplar.is_(True))) or 0
    outliers = db.scalar(select(func.count(VideoPrompt.id)).where(VideoPrompt.is_outlier.is_(True))) or 0
    by_source = {
        source: count for source, count in db.execute(
            select(VideoPrompt.source, func.count(VideoPrompt.id)).group_by(VideoPrompt.source)
        ).all()
    }
    last = db.scalar(select(func.max(VideoPrompt.collected_at)))
    base = rag.baseline(db)
    renders_done = db.scalar(select(func.count(PromptRender.id)).where(PromptRender.status == 'done')) or 0
    reels_done = db.scalar(select(func.count(PromptRender.id)).where(PromptRender.reel_key.is_not(None))) or 0
    reels_failed = db.scalar(select(func.count(PromptRender.id)).where(PromptRender.reel_error.is_not(None))) or 0
    return {
        'total': total,
        'scored': scored,
        'pending_score': total - scored,
        'posted': posted,
        'exemplars': exemplars,
        'outliers': outliers,
        'by_source': by_source,
        'shortlisted_today': len(pipeline.shortlist_for_day(db, today_day)),
        'renders_done': renders_done,
        'reels_done': reels_done,
        'reels_failed': reels_failed,
        # Which video engine THIS machine composes reels with (ffmpeg binary
        # found anywhere / PyAV / OpenCV) and everywhere it looked — readable
        # from the phone, no shell needed (2026-09-10).
        'reel_engine': reel_engines.describe_engine(),
        'baseline_mean': base.mean,
        'baseline_std': base.std,
        'last_collected_at': last.isoformat() if last else None,
    }


@router.get('/renders/{render_id}')
def render_status(render_id: int, db: Session = Depends(get_db)):
    render = db.get(PromptRender, int(render_id))
    if render is None:
        raise HTTPException(404, 'render not found')
    return _serialize_render(render)


@router.get('/{prompt_id}')
def one(prompt_id: int, db: Session = Depends(get_db)):
    return pipeline.serialize_prompt(_get_prompt(db, prompt_id), full=True)


# --------------------------------------------------------------- actions

class ScanIn(BaseModel):
    force: bool = False
    inline: bool = False


@router.post('/scan')
def scan(payload: ScanIn | None = None, db: Session = Depends(get_db)):
    """Run the daily pipeline now. inline=True runs in this process (dev /
    tests); default hands it to the Celery worker."""
    payload = payload or ScanIn()
    if payload.inline:
        summary = pipeline.run_daily(db, force=payload.force)
        return {'queued': False, **summary}
    from app.tasks import daily_prompt_pipeline

    try:
        daily_prompt_pipeline.delay(force=payload.force)
    except Exception as exc:
        raise HTTPException(503, f'worker queue unavailable: {exc}') from exc
    return {'queued': True}


class IngestIn(BaseModel):
    text: str
    author: str | None = None
    source_url: str | None = None


@router.post('/ingest', status_code=201)
def ingest(payload: IngestIn, db: Session = Depends(get_db)):
    """Manual add (owner /addprompt). Scored right away when Ollama is open."""
    candidate = manual_candidate(payload.text, author=payload.author, source_url=payload.source_url)
    if candidate is None:
        raise HTTPException(422, 'that text does not read as a video prompt (needs camera/lighting + product/motion detail, 180+ chars)')
    row, outcome = pipeline.ingest(db, candidate)
    if row is None:
        raise HTTPException(422, 'rejected')
    if outcome == 'created':
        pipeline.score_prompt(db, row)
    db.commit()
    db.refresh(row)
    return {'outcome': outcome, 'prompt': pipeline.serialize_prompt(row, full=True)}


class RatingIn(BaseModel):
    rating: int


@router.post('/{prompt_id}/rate')
def rate(prompt_id: int, payload: RatingIn, db: Session = Depends(get_db)):
    if not 1 <= int(payload.rating) <= 5:
        raise HTTPException(422, 'rating must be 1–5')
    row = pipeline.record_rating(db, _get_prompt(db, prompt_id), payload.rating)
    db.commit()
    db.refresh(row)
    return pipeline.serialize_prompt(row)


class PerformanceIn(BaseModel):
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None
    views: int | None = None


@router.post('/{prompt_id}/performance')
def performance(prompt_id: int, payload: PerformanceIn, db: Session = Depends(get_db)):
    metrics = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not metrics:
        raise HTTPException(422, 'send at least one of likes, comments, saves, shares, views')
    row = pipeline.record_performance(db, _get_prompt(db, prompt_id), metrics)
    db.commit()
    db.refresh(row)
    return pipeline.serialize_prompt(row)


@router.post('/{prompt_id}/posted')
def posted(prompt_id: int, db: Session = Depends(get_db)):
    row = pipeline.mark_posted(db, _get_prompt(db, prompt_id))
    db.commit()
    db.refresh(row)
    return pipeline.serialize_prompt(row)


class RenderIn(BaseModel):
    image_base64: str
    chat_id: str | None = None
    content_type: str = 'image/jpeg'


def _serialize_render(render: PromptRender) -> dict:
    return {
        'id': render.id,
        'prompt_id': render.prompt_id,
        'status': render.status,
        'error': render.error,
        'model': render.model,
        'product_image_key': render.product_image_key,
        'product_image_url': video_creator.public_url(render.product_image_key) if render.product_image_key else None,
        'card_image_key': render.card_image_key,
        'card_image_url': video_creator.public_url(render.card_image_key) if render.card_image_key else None,
        'video_key': render.video_key,
        'video_url': render.video_url,
        'reel_key': render.reel_key,
        'reel_url': render.reel_url,
        'reel_error': render.reel_error,
        'requested_at': render.requested_at.isoformat() if render.requested_at else None,
        'finished_at': render.finished_at.isoformat() if render.finished_at else None,
    }


@router.post('/{prompt_id}/render', status_code=201)
def render(prompt_id: int, payload: RenderIn, db: Session = Depends(get_db)):
    """Approved: store the product image, render the Instagram card now,
    queue the AI video. Returns the render row the bot polls."""
    from PIL import Image

    from app.prompts import post_card

    prompt = _get_prompt(db, prompt_id)
    try:
        data = base64.b64decode(payload.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, 'image_base64 is not valid base64') from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, 'image must be 1 byte – 12 MB')
    try:
        hero = Image.open(BytesIO(data))
        hero.load()
    except Exception as exc:
        raise HTTPException(422, 'image is not a readable picture') from exc

    suffix = 'png' if 'png' in (payload.content_type or '').lower() else 'jpg'
    image_key = video_creator.asset_key('product', prompt_id=prompt.id, suffix=suffix)
    video_creator.store_bytes(image_key, data, content_type=payload.content_type or 'image/jpeg')

    card = post_card.render_card(
        prompt.text,
        hero=hero,
        keyword=post_card.keyword_for(prompt.category, prompt.title),
    )
    buffer = BytesIO()
    card.save(buffer, format='PNG', optimize=True)
    card_key = video_creator.asset_key('card', prompt_id=prompt.id, suffix='png')
    video_creator.store_bytes(card_key, buffer.getvalue(), content_type='image/png')

    row = PromptRender(
        prompt_id=prompt.id,
        chat_id=payload.chat_id,
        product_image_key=image_key,
        card_image_key=card_key,
        status='queued',
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    from app.tasks import render_prompt_video

    try:
        render_prompt_video.delay(row.id)
    except Exception as exc:
        row.status = 'failed'
        row.error = f'worker queue unavailable: {exc}'
        db.commit()
    return _serialize_render(row)
