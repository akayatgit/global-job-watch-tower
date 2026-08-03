"""Filter scraped jobs by title relevance using the local Ollama model.

The searched role (e.g. "ai product owner") must actually match the job
title. Irrelevant jobs are not stored.

Ollama is the normal path (quality data). Keyword filter is Plan B ONLY
for critical heat or missing NVIDIA — never for convenience. Keyword
matching corrupts relevance and must stay rare.
"""

import json
import logging
import re
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

PROMPT = """You judge job TITLE match only.

Search role: "{keywords}"

Rule: true = same role (Senior/Lead/II/III ok). false = different job.
Example for 3 titles: {{"relevant": [true, false, true]}}

Titles ({n} lines — answer with exactly {n} booleans):
{titles}

Reply JSON only — an ARRAY of length {n} under "relevant".
Never a single true/false. Never prose.
{{"relevant": [/* {n} booleans */]}}"""

STRICT_PROMPT = """OUTPUT FORMAT ERROR last time. Fix it.

Role: "{keywords}"
Return ONLY: {{"relevant": [b1, b2, ...]}} with EXACTLY {n} booleans.

Example shape for {n}: {{"relevant": [{example_bools}]}}

Titles:
{titles}

JSON now:"""

ONE_PROMPT = """Is this job title the same role as "{keywords}"?
Title: {title}
Senior/Lead/II ok. Different job = false.
JSON only: {{"relevant": true}} or {{"relevant": false}}"""


def _fallback_verdicts(titles: list[str], keywords: str) -> list[bool]:
    """Keyword heuristic — Plan B only. Prefer rejecting over false keeps."""
    kw = keywords.lower().strip()
    tokens = [t for t in kw.split() if len(t) > 1]
    out = []
    for title in titles:
        tl = title.lower()
        if tokens and all(t in tl for t in tokens):
            out.append(True)
        elif kw and kw in tl:
            out.append(True)
        else:
            out.append(False)
    return out


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ('true', 'yes', '1', 'relevant', 'keep'):
            return True
        if s in ('false', 'no', '0', 'irrelevant', 'reject', 'drop'):
            return False
    raise ValueError(f'not a boolean: {v!r}')


def _parse_verdicts(content: str, n: int) -> list[bool]:
    text = (content or '').strip()
    if not text:
        raise ValueError('empty model reply')

    # Prefer JSON object/array extraction
    payload = None
    start_obj = text.find('{')
    end_obj = text.rfind('}')
    start_arr = text.find('[')
    end_arr = text.rfind(']')

    if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
        try:
            payload = json.loads(text[start_obj:end_obj + 1])
        except json.JSONDecodeError:
            payload = None
    if payload is None and start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        try:
            payload = json.loads(text[start_arr:end_arr + 1])
        except json.JSONDecodeError:
            payload = None
    if payload is None:
        # Last chance: pull a bare list of true/false tokens
        toks = re.findall(r'\b(true|false)\b', text, flags=re.I)
        if len(toks) == n:
            return [t.lower() == 'true' for t in toks]
        raise ValueError('no JSON object/array in model reply')

    verdicts = payload
    if isinstance(payload, dict):
        for key in ('relevant', 'relevance', 'keep', 'matches', 'results', 'verdicts'):
            if key in payload:
                verdicts = payload[key]
                break
        else:
            # {"1": true, "2": false, ...}
            try:
                verdicts = [payload[str(i)] for i in range(1, n + 1)]
            except KeyError as exc:
                raise ValueError(f'expected {n} keyed verdicts') from exc

    if isinstance(verdicts, bool):
        if n == 1:
            return [verdicts]
        raise ValueError(f'expected {n} verdicts, got single bool {verdicts!r}')

    if isinstance(verdicts, dict):
        try:
            verdicts = [verdicts[str(i)] for i in range(1, n + 1)]
        except KeyError as exc:
            raise ValueError(f'expected {n} keyed verdicts') from exc

    if not isinstance(verdicts, list):
        raise ValueError(f'expected list of {n} verdicts, got {type(verdicts).__name__}')

    if len(verdicts) != n:
        raise ValueError(f'expected {n} verdicts, got {len(verdicts)}')

    return [_as_bool(v) for v in verdicts]


def _prompt_for(titles: list[str], keywords: str) -> str:
    numbered = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(titles))
    return PROMPT.format(keywords=keywords, titles=numbered, n=len(titles))


def _strict_prompt_for(titles: list[str], keywords: str) -> str:
    n = len(titles)
    numbered = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(titles))
    # Alternating example so model sees an array, not one bool
    example = ', '.join('true' if i % 2 == 0 else 'false' for i in range(n))
    return STRICT_PROMPT.format(
        keywords=keywords, titles=numbered, n=n, example_bools=example,
    )


def _with_timeout(fn, timeout_s: float):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        return future.result(timeout=timeout_s)


def _chat_json(prompt: str, *, num_predict: int) -> str:
    response = ollama.chat(
        model=config.OLLAMA_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        format='json',
        think=False,
        options={
            'temperature': 0,
            'num_ctx': 1536,
            'num_predict': num_predict,
        },
    )
    return response['message']['content']


def _stream_verdicts(titles: list[str], keywords: str, run_id: int | None) -> list[bool]:
    stream = ollama.chat(
        model=config.OLLAMA_MODEL,
        messages=[{'role': 'user', 'content': _prompt_for(titles, keywords)}],
        stream=True,
        think=True,
        options={
            'temperature': 0,
            'num_ctx': 1536,
            'num_predict': 320,
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
    n = len(titles)
    # ~6 tokens per bool + JSON wrapper; keep headroom for small models
    num_predict = max(96, 24 + n * 8)
    return _parse_verdicts(
        _chat_json(_prompt_for(titles, keywords), num_predict=num_predict),
        n,
    )


def _strict_verdicts(titles: list[str], keywords: str) -> list[bool]:
    n = len(titles)
    num_predict = max(96, 24 + n * 8)
    return _parse_verdicts(
        _chat_json(_strict_prompt_for(titles, keywords), num_predict=num_predict),
        n,
    )


def _one_by_one_verdicts(titles: list[str], keywords: str,
                         run_id: int | None, bi: int, total: int) -> list[bool]:
    """Last Ollama resort — one title per call. Still not keyword Plan B."""
    out: list[bool] = []
    console_log(
        'ai',
        f'Batch {bi}/{total}: falling back to one-by-one Ollama ({len(titles)} titles)…',
        run_id=run_id, level='warn',
    )
    for title in titles:
        try:
            raw = _with_timeout(
                lambda t=title: _chat_json(
                    ONE_PROMPT.format(keywords=keywords, title=t),
                    num_predict=32,
                ),
                min(30.0, config.OLLAMA_TIMEOUT_S),
            )
            out.append(_parse_verdicts(raw, 1)[0])
        except Exception as exc:
            logger.warning('one-by-one failed for %r (%s); reject', title[:60], exc)
            out.append(False)
    return out


def _verdicts_for_batch(titles: list[str], keywords: str,
                        run_id: int | None, bi: int, total: int) -> list[bool]:
    """Ollama only. Parse-fail → strict retry → one-by-one → reject titles.
    Never silent keyword outside Plan B heat path."""
    timeout = config.OLLAMA_TIMEOUT_S

    def _attempt_plain() -> list[bool]:
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
        return _attempt_plain()
    except Exception as exc:
        logger.warning('batch %s parse/call failed (%s); strict retry', bi, exc)
        console_log(
            'ai',
            f'Batch {bi}/{total}: bad JSON ({exc}); strict array retry…',
            run_id=run_id, level='warn',
        )
        try:
            return _with_timeout(
                lambda: _strict_verdicts(titles, keywords),
                timeout,
            )
        except Exception as exc2:
            logger.warning('batch %s strict failed (%s); one-by-one', bi, exc2)
            try:
                return _one_by_one_verdicts(titles, keywords, run_id, bi, total)
            except Exception as exc3:
                logger.warning('batch %s one-by-one failed (%s); reject', bi, exc3)
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


def filter_relevant(
    jobs: list[ParsedJob],
    keywords: str,
    run_id: int | None = None,
    on_kept=None,
) -> tuple[list[ParsedJob], list[ParsedJob]]:
    """Split jobs into (relevant, rejected) based on title vs searched role.

    ``on_kept(kept_jobs)`` is called after each Ollama/keyword batch so the
    tower can persist kept jobs immediately (not only after all batches).
    """
    if not jobs:
        return [], []

    mode = config.RELEVANCE_MODE
    # Explicit keyword mode is legacy emergency override — still Plan B
    if mode in ('keyword', 'keywords', 'off', 'cool'):
        return _keyword_filter(jobs, keywords, run_id, 'forced Plan B mode')

    # ollama / auto / gpu: quality path — cool first; Plan B only after retries
    thermal.wait_for_breath(run_id, why='pre-filter')
    if not thermal.wait_for_ollama_ready(run_id):
        return _keyword_filter(jobs, keywords, run_id, 'critical heat / no GPU')

    batch_size = max(3, config.OLLAMA_BATCH_SIZE)
    # Small models stay accurate with tighter batches
    if '4b' in config.OLLAMA_MODEL.lower():
        batch_size = min(batch_size, 5)
    snap = thermal.snapshot()
    if snap.level == 'warm':
        batch_size = max(3, batch_size - 2)
    elif snap.level == 'hot':
        batch_size = max(3, batch_size // 2)

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
        if not thermal.ollama_path_open():
            # Prefer multi-round cool-down over keyword mid-run
            if not thermal.wait_for_ollama_ready(run_id):
                rest = []
                for b in batches[bi - 1:]:
                    rest.extend(b)
                kw_rel, kw_rej = _keyword_filter(
                    rest, keywords, run_id, 'critical heat mid-run Plan B',
                )
                relevant.extend(kw_rel)
                rejected.extend(kw_rej)
                if kw_rel and on_kept is not None:
                    try:
                        on_kept(kw_rel)
                    except Exception as exc:
                        logger.exception('on_kept callback failed: %s', exc)
                break

        titles = [job.title for job in batch]
        t0 = time.monotonic()
        try:
            verdicts = _verdicts_for_batch(titles, keywords, run_id, bi, len(batches))
            used_ollama = True
        except RuntimeError:
            if thermal.wait_for_ollama_ready(run_id):
                try:
                    verdicts = _verdicts_for_batch(
                        titles, keywords, run_id, bi, len(batches),
                    )
                    used_ollama = True
                except RuntimeError:
                    verdicts = None
            else:
                verdicts = None
            if verdicts is None:
                rest = []
                for b in batches[bi - 1:]:
                    rest.extend(b)
                kw_rel, kw_rej = _keyword_filter(
                    rest, keywords, run_id, 'critical heat during Ollama retry',
                )
                relevant.extend(kw_rel)
                rejected.extend(kw_rej)
                if kw_rel and on_kept is not None:
                    try:
                        on_kept(kw_rel)
                    except Exception as exc:
                        logger.exception('on_kept callback failed: %s', exc)
                break

        kept = [job for job, keep in zip(batch, verdicts) if keep]
        dropped = [job for job, keep in zip(batch, verdicts) if not keep]
        relevant.extend(kept)
        rejected.extend(dropped)
        if kept and on_kept is not None:
            try:
                on_kept(kept)
            except Exception as exc:
                logger.exception('on_kept callback failed: %s', exc)
        kept_preview = ', '.join(j.title[:35] for j in kept[:3])
        drop_preview = ', '.join(j.title[:35] for j in dropped[:3])
        extra = ''
        if kept:
            extra += f' · kept: {kept_preview}' + ('…' if len(kept) > 3 else '')
        if dropped:
            extra += f' · rejected: {drop_preview}' + ('…' if len(dropped) > 3 else '')
        console_log(
            'ai',
            f'Batch {bi}/{len(batches)}: kept {len(kept)}, rejected {len(dropped)}'
            f' in {time.monotonic() - t0:.0f}s{extra}',
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
