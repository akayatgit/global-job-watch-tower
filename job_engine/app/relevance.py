"""Filter scraped jobs by title relevance using the local Ollama model.

The searched role (e.g. "ai product owner") must actually match the job
title. Irrelevant jobs are not stored.

Uses fast JSON mode by default. Between batches, the thermal governor
inserts dynamic breaks so GPU/CPU heat stays under control. On critical
heat or missing NVIDIA, falls back to keyword matching for that round.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

import ollama

from app import config
from app.console import console_log
from app.scraper.parse import ParsedJob
from app import thermal

logger = logging.getLogger(__name__)

FLUSH_EVERY_S = 2.5

PROMPT = """You are filtering job search results.
The user searched for the exact role: "{keywords}".

A job title is RELEVANT only if it is the same role (seniority prefixes,
suffixes like "Senior"/"Lead <role>"/roman numerals, or close wording of the
SAME role are fine). Different roles are NOT relevant, e.g. for
"ai product owner": "Product Owner" is relevant, but "Product Manager",
"Project Manager", "Tech Lead", "Scrum Master", "Business Analyst" are NOT.

Job titles (in order):
{titles}

Reply with ONLY this JSON, with exactly {n} booleans in the same order:
{{"relevant": [true, false, ...]}}"""


def _fallback_verdicts(titles: list[str], keywords: str) -> list[bool]:
    """Keyword heuristic used when Ollama is unavailable or answers badly."""
    kw = keywords.lower().strip()
    core = ' '.join(kw.split()[1:]) if len(kw.split()) > 1 else kw
    return [kw in t.lower() or core in t.lower() for t in titles]


def _parse_verdicts(content: str, n: int) -> list[bool]:
    start = content.find('{')
    end = content.rfind('}')
    if start == -1 or end == -1:
        raise ValueError('no JSON object in model reply')
    payload = json.loads(content[start:end + 1])
    verdicts = payload.get('relevant', payload)
    if isinstance(verdicts, bool):
        raise ValueError(f'expected {n} verdicts, got single bool {verdicts!r}')
    if isinstance(verdicts, dict):
        try:
            verdicts = [verdicts[str(i)] for i in range(1, n + 1)]
        except KeyError as exc:
            raise ValueError(f'expected {n} keyed verdicts') from exc
    if not isinstance(verdicts, list) or len(verdicts) != n:
        raise ValueError(
            f'expected {n} verdicts, got '
            f'{len(verdicts) if isinstance(verdicts, list) else verdicts!r}'
        )
    return [bool(v) for v in verdicts]


def _prompt_for(titles: list[str], keywords: str) -> str:
    numbered = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(titles))
    return PROMPT.format(keywords=keywords, titles=numbered, n=len(titles))


def _with_timeout(fn, timeout_s: float):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        return future.result(timeout=timeout_s)


def _stream_verdicts(titles: list[str], keywords: str, run_id: int | None) -> list[bool]:
    stream = ollama.chat(
        model=config.OLLAMA_MODEL,
        messages=[{'role': 'user', 'content': _prompt_for(titles, keywords)}],
        stream=True,
        think=True,
        options={'temperature': 0, 'num_ctx': 2048},
    )
    thinking_buf = ''
    content = ''
    last_flush = time.monotonic()
    for chunk in stream:
        msg = chunk.get('message') or {}
        thinking_buf += msg.get('thinking') or ''
        content += msg.get('content') or ''
        if thinking_buf and time.monotonic() - last_flush >= FLUSH_EVERY_S:
            console_log('ai', thinking_buf.strip(), run_id=run_id, level='think')
            thinking_buf = ''
            last_flush = time.monotonic()
    if thinking_buf.strip():
        console_log('ai', thinking_buf.strip(), run_id=run_id, level='think')
    return _parse_verdicts(content, len(titles))


def _plain_verdicts(titles: list[str], keywords: str) -> list[bool]:
    response = ollama.chat(
        model=config.OLLAMA_MODEL,
        messages=[{'role': 'user', 'content': _prompt_for(titles, keywords)}],
        format='json',
        think=False,
        options={'temperature': 0, 'num_ctx': 2048},
    )
    return _parse_verdicts(response['message']['content'], len(titles))


def _verdicts_for_batch(titles: list[str], keywords: str,
                        run_id: int | None, bi: int, total: int) -> list[bool]:
    timeout = config.OLLAMA_TIMEOUT_S
    if config.OLLAMA_THINK:
        try:
            return _with_timeout(
                lambda: _stream_verdicts(titles, keywords, run_id),
                timeout,
            )
        except Exception as exc:
            logger.warning('streamed batch %s failed (%s); retrying plain', bi, exc)
            console_log(
                'ai',
                f'Batch {bi}/{total}: thinking mode failed ({exc}); '
                'retrying fast JSON…',
                run_id=run_id, level='warn',
            )
    try:
        return _with_timeout(lambda: _plain_verdicts(titles, keywords), timeout)
    except FuturesTimeout:
        logger.warning('batch %s timed out after %ss', bi, timeout)
        console_log(
            'ai',
            f'Batch {bi}/{total}: Ollama timed out after {int(timeout)}s; '
            'using keyword fallback for this batch.',
            run_id=run_id, level='warn',
        )
        return _fallback_verdicts(titles, keywords)
    except Exception as exc:
        logger.warning('plain batch %s failed (%s); keyword fallback', bi, exc)
        console_log(
            'ai',
            f'Batch {bi}/{total}: Ollama failed ({exc}); '
            'using keyword fallback for this batch.',
            run_id=run_id, level='warn',
        )
        return _fallback_verdicts(titles, keywords)


def _keyword_filter(jobs: list[ParsedJob], keywords: str,
                    run_id: int | None, reason: str):
    titles = [j.title for j in jobs]
    verdicts = _fallback_verdicts(titles, keywords)
    relevant = [j for j, keep in zip(jobs, verdicts) if keep]
    rejected = [j for j, keep in zip(jobs, verdicts) if not keep]
    console_log(
        'ai',
        f'Keyword filter ({reason}): kept {len(relevant)} of {len(jobs)} '
        f'title(s) for "{keywords}".',
        run_id=run_id,
    )
    return relevant, rejected


def filter_relevant(jobs: list[ParsedJob], keywords: str,
                    run_id: int | None = None) -> tuple[list[ParsedJob], list[ParsedJob]]:
    """Split jobs into (relevant, rejected) based on title vs searched role."""
    if not jobs:
        return [], []

    mode = config.RELEVANCE_MODE
    if mode in ('keyword', 'keywords', 'off', 'cool'):
        return _keyword_filter(jobs, keywords, run_id, 'forced cool mode')

    # auto / ollama: respect thermal governor
    use_ollama = mode in ('ollama', 'auto', 'gpu')
    if use_ollama and not thermal.allow_ollama(run_id):
        return _keyword_filter(jobs, keywords, run_id, 'thermal/GPU guard')

    batch_size = max(4, config.OLLAMA_BATCH_SIZE)
    snap = thermal.snapshot()
    if snap.level == 'warm':
        batch_size = max(4, batch_size - 2)
    elif snap.level == 'hot':
        batch_size = max(4, batch_size // 2)

    batches = [jobs[i:i + batch_size] for i in range(0, len(jobs), batch_size)]
    console_log(
        'ai',
        f'Checking {len(jobs)} title(s) against "{keywords}" with '
        f'{config.OLLAMA_MODEL} (fast JSON, heat={snap.level} {snap.detail}) '
        f'in {len(batches)} batch(es) of ~{batch_size}…',
        run_id=run_id,
    )

    relevant: list[ParsedJob] = []
    rejected: list[ParsedJob] = []

    for bi, batch in enumerate(batches, start=1):
        # Dynamic break before every batch (including first — lets GPU settle
        # after Chrome dwell). Longer when warm/hot.
        thermal.wait_for_breath(run_id, why=f'batch {bi}/{len(batches)}')
        if not thermal.allow_ollama(run_id):
            # Finish the rest with keyword so we don't keep heating
            rest = []
            for b in batches[bi - 1:]:
                rest.extend(b)
            kw_rel, kw_rej = _keyword_filter(
                rest, keywords, run_id, 'thermal cutover mid-run',
            )
            relevant.extend(kw_rel)
            rejected.extend(kw_rej)
            break

        titles = [job.title for job in batch]
        t0 = time.monotonic()
        verdicts = _verdicts_for_batch(titles, keywords, run_id, bi, len(batches))
        kept = [job for job, keep in zip(batch, verdicts) if keep]
        dropped = [job for job, keep in zip(batch, verdicts) if not keep]
        relevant.extend(kept)
        rejected.extend(dropped)
        console_log(
            'ai',
            f'Batch {bi}/{len(batches)}: kept {len(kept)}, rejected {len(dropped)}'
            f' in {time.monotonic() - t0:.0f}s'
            + (f' ({", ".join(j.title[:35] for j in dropped[:4])}'
               + ('…' if len(dropped) > 4 else '') + ')' if dropped else ''),
            run_id=run_id,
        )

    console_log(
        'ai',
        f'Relevance done: keeping {len(relevant)} of {len(jobs)} title(s), '
        f'rejected {len(rejected)}.',
        run_id=run_id,
    )
    return relevant, rejected
