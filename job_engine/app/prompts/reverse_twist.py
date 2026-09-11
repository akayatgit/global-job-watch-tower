"""Magic pencil — twist a reverse prompt and its cut-reference frames.

Ashok (2026-09-11): recreating a best-performing clip is only half the
product. After the original prompt exists, one imaginative line must
rewrite every beat (timing, emotion, context) and restyle every
cut-reference still through text+image→image. The original stay intact.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from app import config
from app.prompts.reverse_prompt import (
    COMPRESS_USER,
    DEFAULT_KEYWORD,
    DESCRIBE_BUDGET_S,
    ENGINE_GEMINI,
    MAX_OUTPUT_TOKENS,
    PROMPT_CHAR_LIMIT,
    PROMPT_MAX_CHARS,
    ReferenceFrame,
    ReverseError,
    ReverseReading,
    SEGMENT_RE,
    THINKING_BUDGET,
    _output_text,
    apply_prompt_cap,
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
TWIST_IMAGE_BUDGET_S = 180

TWIST_SYSTEM = """You are the magic pencil. You have a finished timestamped generation prompt that recreates a product video beat-for-beat.

The owner has given ONE imaginative twist. Rewrite the ENTIRE prompt so that twist lives in EVERY detail — not a one-line tag at the end.

You must change, in every timestamped segment:
- timing and pacing (holds, snap-cuts, slow-mo, delayed reveals)
- beat (what physically happens on each cut)
- emotion and tone
- context / world / setting
- imaginative physical detail (materials, light, weather, scale, creatures)

Keep the same timestamp structure and duration coverage so the shot list still maps to the original cut-reference frames. Do not mention "twist", "magic pencil", or "original". Never invent brand names or on-screen text that was not in the draft.

HARD CAP: the `prompt` value MUST be strictly under 3000 characters including spaces. Think first, then write dense cinematic text. Full essence, no filler.

Return STRICT JSON with exactly three keys:
{"keyword": "<ONE uppercase word>", "prompt": "<the rewritten timestamped prompt, under 3000 characters>", "cuts": [{"start": 0.0, "end": 1.8}]}
The JSON object MUST be complete. Never stop mid-sentence."""

TWIST_USER = (
    'Twist (apply everywhere — timing, beat, emotion, context, imagination):\n'
    '{twist}\n\n'
    'Original prompt:\n'
    '---\n{draft}\n---\n'
    'Think, then rewrite every timestamped segment. The prompt string must be '
    'strictly under 3000 characters including spaces. Return only complete JSON.'
)

# Ashok (2026-09-11): keep the edit one line — "Change from x to y, and z".
# Long identity essays made Nano Banana invent a softer, less detailed frame.
FRAME_EDIT_PROMPT = (
    'Change from the source frame to {twist}, and keep pose, lighting, details and identity'
)


def frame_edit_prompt(twist: str) -> str:
    return FRAME_EDIT_PROMPT.format(twist=clean_twist(twist))


def clean_twist(raw: str | None) -> str:
    text = ' '.join((raw or '').split())
    return text[:TWIST_TEXT_MAX]


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
        prompt = (reading.prompt or '').strip()
        if len(prompt) >= PROMPT_CHAR_LIMIT:
            if log:
                log(f'twist prompt {len(prompt)} chars — thinking compress to under {PROMPT_CHAR_LIMIT}')
            compress = dict(inputs)
            compress['prompt'] = COMPRESS_USER.format(n=len(prompt))
            compressed = parse_reading(_output_text(run(model, input=compress)), model=model)
            if compressed.prompt and len(compressed.prompt) < len(prompt):
                reading = compressed
    except Exception as exc:
        logger.warning('Magic-pencil prompt failed: %s', exc)
        return None
    reading = apply_prompt_cap(reading)
    refined = (reading.prompt or '').strip()
    if not refined or len(refined) < max(80, min(int(len(draft) * 0.55), PROMPT_MAX_CHARS // 2)):
        logger.warning('Magic-pencil prompt discarded (empty or too short)')
        return None
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
    """Each original cut JPEG → Nano Banana 2 Lite edit. One-line
    change prompt only — the source image carries the detail."""
    from app.prompts import reverse_prompt, video_creator
    from app.replicate_img import edit_image

    idea = clean_twist(twist)
    if not idea or not frames:
        return [], ['no twist or no frames']
    # Callers still pass the rewritten prompt; the one-line edit does not
    # inject the beat (Ashok: "Change from x to y, and z").
    _ = twisted_prompt
    edit = edit or (lambda prompt, image, **_k: edit_image(prompt, image))
    store = store or video_creator.store_bytes
    key_for = key_for or video_creator.asset_key
    out: list[ReferenceFrame] = []
    failed: list[str] = []
    prompt = frame_edit_prompt(idea)
    for index, frame in enumerate(frames, start=1):
        blob = reverse_prompt.read_reference_jpeg(frame.key, read_asset=read_asset)
        if not blob:
            failed.append(frame.filename or f'{index}')
            continue
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
