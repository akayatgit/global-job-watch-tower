"""Prompt RAG — the memory of what already worked.

Stores one embedding per prompt (JSON column, cosine in Python — thousands
of prompts is nothing) and answers three questions for the scorer:

1. Is this a near-duplicate of something we already hold?  (dedupe)
2. Which proven winners are closest to it?                 (few-shot exemplars)
3. How good are winners on average right now?              (baseline → outlier)

Embeddings come from Ollama (`PROMPT_EMBED_MODEL`). When Ollama is not
reachable (tests, cold host) a deterministic hashed bag-of-words vector is
used instead — worse recall, same shape, never a crash.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import VideoPrompt

logger = logging.getLogger(__name__)

FALLBACK_DIM = 256
DUPLICATE_COSINE = 0.93
EXEMPLAR_K = 3
# A prompt is an outlier when it beats the winners' mean by more than one
# standard deviation (floor 5 points so a tiny baseline can't flag everything)
OUTLIER_SIGMA = 1.0
MIN_STD = 5.0
TOKEN_RE = re.compile(r'[a-z0-9]+')


@dataclass
class Baseline:
    count: int
    mean: float | None
    std: float | None

    def is_outlier(self, score: float | None) -> bool:
        if score is None or self.mean is None or self.count < 3:
            return False
        std = max(self.std or 0.0, MIN_STD)
        return score > self.mean + OUTLIER_SIGMA * std


def hashed_embedding(text: str, dim: int = FALLBACK_DIM) -> list[float]:
    """Deterministic bag-of-words → unit vector. Offline fallback only."""
    vec = [0.0] * dim
    for token in TOKEN_RE.findall((text or '').lower()):
        digest = hashlib.md5(token.encode('utf-8')).digest()
        index = int.from_bytes(digest[:4], 'big') % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def embed(text: str) -> list[float]:
    """Ollama embedding when available, hashed fallback otherwise."""
    from app import config

    try:
        import ollama

        response = ollama.embeddings(
            model=getattr(config, 'PROMPT_EMBED_MODEL', 'nomic-embed-text'),
            prompt=(text or '')[:6000],
        )
        vector = list(response.get('embedding') or [])
        if vector:
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            return [round(v / norm, 6) for v in vector]
    except Exception as exc:  # pragma: no cover - depends on host
        logger.info('embedding fallback (ollama unavailable): %s', exc)
    return hashed_embedding(text)


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def find_duplicate(db: Session, vector: list[float], *, threshold: float = DUPLICATE_COSINE) -> VideoPrompt | None:
    """Nearest stored prompt above the duplicate threshold, else None."""
    best: tuple[float, VideoPrompt] | None = None
    rows = db.execute(
        select(VideoPrompt).where(VideoPrompt.embedding.is_not(None))
    ).scalars().all()
    for row in rows:
        sim = cosine(vector, row.embedding)
        if sim >= threshold and (best is None or sim > best[0]):
            best = (sim, row)
    return best[1] if best else None


def exemplars(db: Session, vector: list[float] | None, *, k: int = EXEMPLAR_K) -> list[VideoPrompt]:
    """Proven winners nearest to this prompt — few-shot anchors for scoring.
    Falls back to the best-performing winners when nothing is embedded."""
    rows = db.execute(
        select(VideoPrompt).where(VideoPrompt.exemplar.is_(True))
    ).scalars().all()
    if not rows:
        return []
    if vector:
        rows.sort(key=lambda row: cosine(vector, row.embedding), reverse=True)
    else:
        rows.sort(key=lambda row: (row.performance_score or 0.0, row.final_score or 0.0), reverse=True)
    return rows[:k]


def baseline(db: Session) -> Baseline:
    """Mean/std of winners' final scores. Empty RAG → no baseline yet."""
    scores = [
        float(score) for (score,) in db.execute(
            select(VideoPrompt.final_score).where(
                VideoPrompt.exemplar.is_(True), VideoPrompt.final_score.is_not(None),
            )
        ).all()
    ]
    if not scores:
        return Baseline(count=0, mean=None, std=None)
    mean = statistics.fmean(scores)
    std = statistics.pstdev(scores) if len(scores) > 1 else 0.0
    return Baseline(count=len(scores), mean=round(mean, 2), std=round(std, 2))


def performance_score(rating: int | None, performance: dict | None) -> float | None:
    """One number from owner rating + Instagram numbers (all optional).

    rating 1–5 → 0–60; engagement → up to 40 on a log scale so a viral post
    does not dwarf everything forever. None when nothing is known.
    """
    have_any = False
    total = 0.0
    if rating:
        have_any = True
        total += max(0, min(5, int(rating))) * 12.0
    perf = performance or {}
    likes = float(perf.get('likes') or 0)
    comments = float(perf.get('comments') or 0)
    saves = float(perf.get('saves') or 0)
    shares = float(perf.get('shares') or 0)
    views = float(perf.get('views') or 0)
    engagement = likes + 3 * comments + 4 * saves + 4 * shares + views / 100.0
    if engagement > 0:
        have_any = True
        total += min(40.0, 8.0 * math.log10(1 + engagement))
    return round(total, 1) if have_any else None


def promote_winners(db: Session, *, min_performance: float = 24.0, min_rating: int = 4) -> int:
    """Mark proven prompts as exemplars: rated ≥4 by Ashok OR strong
    engagement (24 pts ≈ 1,000 weighted interactions on the log scale).
    Idempotent — returns how many rows changed."""
    changed = 0
    rows = db.execute(select(VideoPrompt).where(VideoPrompt.exemplar.is_(False))).scalars().all()
    for row in rows:
        strong = (row.rating or 0) >= min_rating or (row.performance_score or 0.0) >= min_performance
        if strong:
            row.exemplar = True
            changed += 1
    return changed
