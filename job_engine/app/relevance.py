"""Filter scraped jobs by title relevance using the local Ollama model.

The searched role (e.g. "ai product owner") must actually match the job
title. Irrelevant jobs are not stored.

Ollama is the normal path (quality data). Keyword filter is Plan B ONLY
for critical heat or missing NVIDIA — never for convenience. Keyword
matching corrupts relevance and must stay rare.
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
from app.tower_health import record_event_standalone

logger = logging.getLogger(__name__)

FLUSH_EVERY_S = 2.5

PROMPT = """Fast title match. Search role: "{keywords}".

Keep true ONLY if the title is the same role (Senior/Lead/II ok).
Different jobs = false. No explanations. No thinking aloud.

Titles:
{titles}

JSON only, exactly {n} booleans:
{{"relevant": [true, false, ...]}}"""


def _fallback_verdicts(titles: list[str], keywords: str) -> list[bool]:
    """Keyword heuristic — Plan B only. Prefer rejecting over false keeps."""
    kw = keywords.lower().strip()
    tokens = [t for t in kw.split() if len(t) > 1]
    out = []
    for title in titles:
        tl = title.lower()
        # All significant tokens must appear — stricter than substring guess
        if tokens and all(t in tl for t in tokens):
            out.append(True)
        elif kw and kw in tl:
            out.append(True)
        else:
            out.append(False)
    return out


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
        options={
            'temperature': 0,
            'num_ctx': 1024,
            'num_predict': 256,
        },
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
        options={
            'temperature': 0,
            'num_ctx': 1024,
            'num_predict': 128,
        },
    )
    return _parse_verdicts(response['message']['content'], len(titles))


def _verdicts_for_batch(titles: list[str], keywords: str,
                        run_id: int | None, bi: int, total: int) -> list[bool]:
    """Ollama only. On failure: one heat-break retry, then reject the batch
    (do not silently keyword — that corrupts data outside Plan B)."""
    timeout = config.OLLAMA_TIMEOUT_S

    def _attempt(label: str) -> list[bool]:
        if config.OLLAMA_THINK:
            try:
                return _with_timeout(
                    lambda: _stream_verdicts(titles, keywords, run_id),
                    timeout,
                )
            except Exception as exc:
                logger.warning('streamed batch %s failed (%s); plain', bi, exc)
                console_log(
                    'ai',
                    f'Batch {bi}/{total}: thinking mode failed ({exc}); '
                    'retrying fast JSON…',
                    run_id=run_id, level='warn',
                )
        return _with_timeout(lambda: _plain_verdicts(titles, keywords), timeout)

    try:
        return _attempt('first')
    except Exception as exc:
        logger.warning('batch %s failed (%s); cooling then one retry', bi, exc)
        console_log(
            'ai',
            f'Batch {bi}/{total}: Ollama hiccup ({exc}); heat break then one retry…',
            run_id=run_id, level='warn',
        )
        thermal.wait_for_breath(run_id, why=f'ollama retry batch {bi}')
        if not thermal.allow_ollama(run_id):
            raise RuntimeError('critical heat during Ollama retry') from exc
        try:
            return _attempt('retry')
        except Exception as exc2:
            logger.warning('batch %s retry failed (%s); rejecting batch', bi, exc2)
            console_log(
                'ai',
                f'Batch {bi}/{total}: Ollama still failing — rejecting these '
                f'{len(titles)} title(s) rather than keyword-corrupting data.',
                run_id=run_id, level='warn',
            )
            return [False] * len(titles)


def _keyword_filter(jobs: list[ParsedJob], keywords: str,
                    run_id: int | None, reason: str):
    titles = [j.title for j in jobs]
    verdicts = _fallback_verdicts(titles, keywords)
    relevant = [j for j, keep in zip(jobs, verdicts) if keep]
    rejected = [j for j, keep in zip(jobs, verdicts) if not keep]
    console_log(
        'ai',
        f'Plan B keyword filter ({reason}): kept {len(relevant)} of {len(jobs)} '
        f'title(s) for "{keywords}". Use only under critical heat / no GPU.',
        run_id=run_id, level='warn',
    )
    record_event_standalone(
        'keyword_filter',
        run_id=run_id,
        detail=f'{reason}; kept {len(relevant)}/{len(jobs)}',
    )
    try:
        from app.runtime_settings import mark_plan_b_active
        mark_plan_b_active(run_id=run_id, detail=reason)
    except Exception:
        pass
    return relevant, rejected


def filter_relevant(jobs: list[ParsedJob], keywords: str,
                    run_id: int | None = None) -> tuple[list[ParsedJob], list[ParsedJob]]:
    """Split jobs into (relevant, rejected) based on title vs searched role."""
    if not jobs:
        return [], []

    mode = config.RELEVANCE_MODE
    # Explicit keyword mode is legacy emergency override — still Plan B
    if mode in ('keyword', 'keywords', 'off', 'cool'):
        return _keyword_filter(jobs, keywords, run_id, 'forced Plan B mode')

    # ollama / auto / gpu: quality path
    if not thermal.allow_ollama(run_id):
        return _keyword_filter(jobs, keywords, run_id, 'critical heat / no GPU')

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
        f'{config.OLLAMA_MODEL} (heat={snap.level} {snap.detail}) '
        f'in {len(batches)} batch(es) of ~{batch_size}…',
        run_id=run_id,
    )

    relevant: list[ParsedJob] = []
    rejected: list[ParsedJob] = []
    used_ollama = False

    for bi, batch in enumerate(batches, start=1):
        thermal.wait_for_breath(run_id, why=f'batch {bi}/{len(batches)}')
        if not thermal.allow_ollama(run_id):
            # Cool down once more before Plan B — prefer waiting over keyword
            console_log(
                'ai',
                'Heat still critical — extra cool-down before Plan B…',
                run_id=run_id, level='warn',
            )
            time.sleep(max(60.0, config.HEAT_BREAK_CRITICAL_S))
            if not thermal.allow_ollama(run_id):
                rest = []
                for b in batches[bi - 1:]:
                    rest.extend(b)
                kw_rel, kw_rej = _keyword_filter(
                    rest, keywords, run_id, 'critical heat mid-run Plan B',
                )
                relevant.extend(kw_rel)
                rejected.extend(kw_rej)
                break
            # cooled enough — continue Ollama

        titles = [job.title for job in batch]
        t0 = time.monotonic()
        try:
            verdicts = _verdicts_for_batch(titles, keywords, run_id, bi, len(batches))
            used_ollama = True
        except RuntimeError:
            rest = []
            for b in batches[bi - 1:]:
                rest.extend(b)
            kw_rel, kw_rej = _keyword_filter(
                rest, keywords, run_id, 'critical heat during Ollama retry',
            )
            relevant.extend(kw_rel)
            rejected.extend(kw_rej)
            break

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
        record_event_standalone(
            'ollama_batch',
            run_id=run_id,
            detail=f'{bi}/{len(batches)} kept {len(kept)}/{len(batch)}',
        )

    if used_ollama:
        record_event_standalone(
            'ollama_filter',
            run_id=run_id,
            detail=f'kept {len(relevant)}/{len(jobs)} for {keywords[:80]}',
        )
        from app.runtime_settings import clear_plan_b
        clear_plan_b()  # Plan A restored — drop orange banner immediately

    console_log(
        'ai',
        f'Relevance done: keeping {len(relevant)} of {len(jobs)} title(s), '
        f'rejected {len(rejected)}.',
        run_id=run_id,
    )
    return relevant, rejected
