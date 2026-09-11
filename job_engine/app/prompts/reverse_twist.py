"""Magic pencil — twist a reverse prompt and its cut-reference frames.

Ashok (2026-09-11): recreating a best-performing clip is only half the
product. After the original prompt exists, one imaginative line must
rewrite every beat (timing, emotion, context) and restyle every
cut-reference still through text+image→image. The original stay intact.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

from app import config
from app.prompts.reverse_prompt import (
    DEFAULT_KEYWORD,
    DESCRIBE_BUDGET_S,
    ENGINE_GEMINI,
    MAX_OUTPUT_TOKENS,
    ReferenceFrame,
    ReverseError,
    ReverseReading,
    SEGMENT_RE,
    THINKING_BUDGET,
    _output_text,
    clean_keyword,
    jpeg_data_uri,
    json_reading_complete,
    parse_reading,
    serialize_reference_frames,
    vision_api_model,
    vision_key_missing,
)

logger = logging.getLogger(__name__)

TWIST_TEXT_MAX = 400
TWIST_PROMPT_MAX = 3000
TWIST_IMAGE_BUDGET_S = 180
STYLE_LINE_RE = re.compile(r'(?im)(?:^|\n)(style:\s*.+)$')

TWIST_SYSTEM = """You are the magic pencil. You have a finished timestamped generation prompt that recreates a product video beat-for-beat.

The owner has given ONE imaginative twist. Rewrite the ENTIRE prompt so that twist lives in EVERY detail — not a one-line tag at the end.

You must change, in every timestamped segment:
- timing and pacing (holds, snap-cuts, slow-mo, delayed reveals)
- beat (what physically happens on each cut)
- emotion and tone
- context / world / setting
- imaginative physical detail (materials, light, weather, scale, creatures)

Keep the same timestamp structure and duration coverage so the shot list still maps to the original cut-reference frames. Do not mention "twist", "magic pencil", or "original". Never invent brand names or on-screen text that was not in the draft.

HARD CAP: the `prompt` value MUST be at most 3000 characters including spaces. Dense, cinematic, no filler. Capture the full essence — every timestamp, camera, product, action, emotion, world, and the twist — in that budget. End with one "Style:" line that locks the look for every recreate frame (palette, materials, lighting grammar, era). Same film, same product identity across all stills.

Return STRICT JSON with exactly three keys:
{"keyword": "<ONE uppercase word>", "prompt": "<the rewritten timestamped prompt, ≤3000 characters>", "cuts": [{"start": 0.0, "end": 1.8}]}
The JSON object MUST be complete. Never stop mid-sentence."""

TWIST_USER = (
    'Twist (apply everywhere — timing, beat, emotion, context, imagination):\n'
    '{twist}\n\n'
    'Original prompt:\n'
    '---\n{draft}\n---\n'
    'Rewrite every timestamped segment. The prompt string must be ≤3000 characters '
    'including spaces and still hold the full essence. Return only complete JSON.'
)

TWIST_COMPRESS_USER = (
    'The rewrite is {n} characters — too long. Compress it to AT MOST 3000 characters '
    'including spaces. Keep every timestamp. Keep the twist in every beat. Keep camera, '
    'product, action, emotion, world. No filler. End with one Style: line that locks the '
    'look for all frames. Return only complete JSON.'
)

FRAME_EDIT_PROMPT = (
    'SERIES LOCK — this is frame {index} of {total} from ONE film. Same product identity, '
    'same world, same lighting grammar, same colour palette, same materials, same era. '
    'Do not invent a new look for this frame. Only the action and pose at this timestamp change.\n'
    'Shared look: {look}\n'
    'Twist (identical on every frame): {twist}\n'
    'This still is the {time} cut-reference. Keep the same camera, crop, product placement '
    'and composition. The twist must be VISIBLE.\n'
    'This beat only:\n{beat}'
)


def clean_twist(raw: str | None) -> str:
    text = ' '.join((raw or '').split())
    return text[:TWIST_TEXT_MAX]


def extract_style_line(prompt: str) -> str:
    match = STYLE_LINE_RE.search(prompt or '')
    return match.group(1).strip() if match else ''


def series_look(twisted_prompt: str, twist: str) -> str:
    """One shared look string stamped on every still."""
    idea = clean_twist(twist)
    style = extract_style_line(twisted_prompt)
    if style.lower().startswith('style:'):
        style = style.split(':', 1)[1].strip()
    parts = [p for p in (idea, style) if p]
    return ' · '.join(parts) or idea


def _trim_words(text: str, limit: int) -> str:
    if limit <= 0:
        return ''
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0].rstrip(' ,;:.-')
    return cut or text[:limit]


def _split_twist_parts(prompt: str) -> tuple[list[str], str]:
    """Timestamped blocks plus a trailing Style: line."""
    text = (prompt or '').strip()
    style = extract_style_line(text)
    body = text
    if style:
        match = STYLE_LINE_RE.search(text)
        if match:
            body = text[:match.start()].strip()
    matches = list(SEGMENT_RE.finditer(body))
    if not matches:
        return ([body] if body else [], style)
    parts: list[str] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        parts.append(body[match.start():end].strip())
    return parts, style


def fit_twist_prompt(prompt: str, limit: int = TWIST_PROMPT_MAX) -> str:
    """Hard cap including spaces. Keep every timestamp and the Style lock."""
    text = re.sub(r'\n{3,}', '\n\n', (prompt or '').strip())
    if len(text) <= limit:
        return text
    parts, style = _split_twist_parts(text)
    style_line = style if style else ''
    if style_line and not style_line.lower().startswith('style:'):
        style_line = f'Style: {style_line}'
    style_cost = (1 + len(style_line)) if style_line else 0
    budget = max(80, limit - style_cost)

    def total() -> int:
        if not parts:
            return 0
        return sum(len(p) for p in parts) + (len(parts) - 1)

    for _ in range(64):
        if total() <= budget:
            break
        idx = max(range(len(parts)), key=lambda i: len(parts[i]))
        longest = parts[idx]
        header = SEGMENT_RE.match(longest)
        floor = len(header.group(0)) + 1 if header else 24
        if len(longest) <= floor:
            break
        need = total() - budget
        parts[idx] = _trim_words(longest, max(floor, len(longest) - max(need, 16)))
    out = '\n'.join(p for p in parts if p)
    if style_line:
        if len(out) + 1 + len(style_line) <= limit:
            out = f'{out}\n{style_line}' if out else style_line
        else:
            out = _trim_words(out, max(0, limit - len(style_line) - 1))
            out = f'{out}\n{style_line}'.strip()
    if len(out) > limit:
        out = _trim_words(out, limit)
    return out


def _has_timestamps(prompt: str) -> bool:
    return bool(SEGMENT_RE.search(prompt or ''))


def frames_from_stored(raw) -> list[ReferenceFrame]:
    from app.prompts.reverse_prompt import load_reference_frames

    out: list[ReferenceFrame] = []
    for item in load_reference_frames(raw):
        try:
            t = float(item.get('t'))
        except (TypeError, ValueError):
            continue
        key = str(item.get('key') or '')
        if not key:
            continue
        out.append(ReferenceFrame(
            t=t,
            key=key,
            filename=str(item.get('filename') or ''),
        ))
    return out


def segment_for_time(prompt: str, t: float) -> str:
    """The timestamped beat that covers `t`, else the nearest one."""
    best = ''
    best_dist = None
    for match in SEGMENT_RE.finditer(prompt or ''):
        start, end = float(match.group(1)), float(match.group(2))
        if end < start:
            start, end = end, start
        line = match.group(0)
        # include the rest of that line / paragraph
        tail = (prompt or '')[match.end():]
        extra = tail.split('\n', 1)[0].strip()
        body = f'{line} {extra}'.strip() if extra else line
        if start - 0.02 <= t <= end + 0.02:
            return body
        mid = (start + end) / 2
        dist = abs(t - mid)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = body
    return best


def twist_prompt_text(
    prompt: str,
    twist: str,
    *,
    run: Callable[..., object] | None = None,
    log: Callable[[str], None] | None = None,
) -> ReverseReading | None:
    """Gemini second call: rewrite every beat. Text only — the video
    already authored the original. Failure or a much shorter rewrite
    returns None so the original stays."""
    draft = (prompt or '').strip()
    idea = clean_twist(twist)
    if not draft or not idea:
        return None
    user = TWIST_USER.replace('{twist}', idea).replace('{draft}', draft)
    model = vision_api_model(ENGINE_GEMINI)
    if run is None:
        missing = vision_key_missing(ENGINE_GEMINI)
        if missing:
            logger.warning('Magic-pencil prompt skipped: %s', missing)
            return None
        import replicate

        from app.prompts.video_creator import replicate_render

        client = replicate.Client(api_token=config.REPLICATE_API_TOKEN)

        def run(model, input):  # noqa: A001
            return replicate_render(client, model, input=input, budget_s=DESCRIBE_BUDGET_S, log=log)

    inputs = {
        'prompt': user,
        'system_instruction': TWIST_SYSTEM,
        'temperature': 0.85,
        'max_output_tokens': MAX_OUTPUT_TOKENS,
        'thinking_budget': THINKING_BUDGET,
    }
    try:
        output = run(model, input=inputs)
        text = _output_text(output)
        reading = parse_reading(text, model=model)
        if not json_reading_complete(text):
            if log:
                log('twist JSON was truncated — asking once more')
            output = run(model, input=inputs)
            retry = parse_reading(_output_text(output), model=model)
            if len(retry.prompt) > len(reading.prompt):
                reading = retry
        if len((reading.prompt or '')) > TWIST_PROMPT_MAX:
            if log:
                log(f'twist prompt {len(reading.prompt)} chars — compressing to {TWIST_PROMPT_MAX}')
            compress = dict(inputs)
            compress['prompt'] = TWIST_COMPRESS_USER.format(n=len(reading.prompt))
            compressed = parse_reading(_output_text(run(model, input=compress)), model=model)
            if _has_timestamps(compressed.prompt) and len(compressed.prompt) <= len(reading.prompt):
                reading = compressed
    except Exception as exc:
        logger.warning('Magic-pencil prompt failed: %s', exc)
        return None
    refined = fit_twist_prompt((reading.prompt or '').strip(), TWIST_PROMPT_MAX)
    if not refined or not _has_timestamps(refined) or len(refined) < 80:
        logger.warning('Magic-pencil prompt discarded (empty, no timestamps, or too short)')
        return None
    reading.prompt = refined
    if not reading.keyword or reading.keyword == DEFAULT_KEYWORD:
        reading.keyword = clean_keyword(idea.split()[0] if idea else DEFAULT_KEYWORD)
    return reading


def twist_reference_frames(
    frames: list[ReferenceFrame],
    *,
    twist: str,
    twisted_prompt: str,
    prompt_id: int,
    read_asset=None,
    edit: Callable[..., bytes] | None = None,
    store: Callable[..., Path] | None = None,
    key_for: Callable[..., str] | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[list[ReferenceFrame], list[str]]:
    """Each original cut JPEG → nano-banana text+image→image with the twist."""
    from app.prompts import reverse_prompt, video_creator
    from app.replicate_img import edit_image

    idea = clean_twist(twist)
    if not idea or not frames:
        return [], ['no twist or no frames']
    look = series_look(twisted_prompt, idea)
    edit = edit or (lambda prompt, image, **_k: edit_image(prompt, image))
    store = store or video_creator.store_bytes
    key_for = key_for or video_creator.asset_key
    out: list[ReferenceFrame] = []
    failed: list[str] = []
    total = len(frames)
    for index, frame in enumerate(frames, start=1):
        blob = reverse_prompt.read_reference_jpeg(frame.key, read_asset=read_asset)
        if not blob:
            failed.append(frame.filename or f'{index}')
            continue
        beat = segment_for_time(twisted_prompt, frame.t) or twisted_prompt[:400]
        prompt = FRAME_EDIT_PROMPT.format(
            look=look,
            twist=idea,
            index=index,
            total=total,
            time=f'{frame.t:.2f}s',
            beat=beat[:600],
        )
        try:
            data = edit(prompt, blob)
            if not data or len(data) < 64:
                raise ReverseError('empty twisted jpeg')
        except Exception as exc:
            logger.warning('twisted frame %s failed: %s', frame.filename or index, exc)
            failed.append(frame.filename or f'{index}')
            continue
        key = key_for(f'twref{index:02d}', prompt_id=prompt_id, suffix='jpg')
        store(key, data, content_type='image/jpeg')
        name = frame.filename.replace('cut-', 'twist-', 1) if frame.filename.startswith('cut-') else (
            f'twist-{index:02d}-{frame.t:.2f}s.jpg'
        )
        out.append(ReferenceFrame(t=frame.t, key=key, filename=name))
        if log:
            log(f'twisted frame {index}/{len(frames)} at {frame.t:.2f}s')
    return out, failed


def serialize_twist_frames(frames: list[ReferenceFrame]) -> list[dict]:
    return serialize_reference_frames(frames)
