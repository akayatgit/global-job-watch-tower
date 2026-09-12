"""Magic pencil — twist a reverse prompt and its cut-reference frames.

Ashok (2026-09-11): recreating a best-performing clip is only half the
product. After the original prompt exists, one imaginative line must
rewrite every beat (timing, emotion, context) and restyle every
cut-reference still through text+image→image. The original stay intact.
"""

from __future__ import annotations

import io
import logging
import zipfile
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
    ReferenceFrame,
    ReverseError,
    ReverseReading,
    SEGMENT_RE,
    THINKING_BUDGET,
    _output_text,
    apply_prompt_cap,
    clean_keyword,
    cuts_from_prompt,
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
TWIST_VIDEO_MODEL = 'google/gemini-omni-1.1'
OMNI_MAX_S = 10

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


def twist_rewrite_ok(draft: str, refined: str) -> bool:
    """Keep a rewrite that still has the shot list. Length is not a veto —
    under 3000 is the law; a shorter complete beat sheet is fine."""
    refined = (refined or '').strip()
    if len(refined) < 80:
        return False
    need = len(list(SEGMENT_RE.finditer(draft or '')))
    got = len(list(SEGMENT_RE.finditer(refined)))
    return not (need and got == 0)


def fallback_twist_prompt(draft: str, idea: str) -> str:
    """Gemini missed: keep every original beat and stamp the twist on it.
    Stills + Omni can still run. Never mention 'twist' in the text."""
    from app.prompts.reverse_prompt import _split_prompt_parts, fit_prompt

    idea = clean_twist(idea)
    parts, style = _split_prompt_parts(draft)
    if not parts:
        parts = [(draft or '').strip()]
    needle = idea.lower()
    lines: list[str] = []
    for part in parts:
        if not part:
            continue
        if needle and needle in part.lower():
            lines.append(part)
        else:
            lines.append(f'{part.rstrip(" .")} — {idea}.')
    text = '\n'.join(lines)
    if style:
        extra = style if (needle and needle in style.lower()) else f'{style.rstrip(".")}, {idea}'
        text = f'{text}\n{extra}' if text else extra
    return fit_prompt(text)


def twist_prompt_text(
    prompt: str,
    twist: str,
    *,
    run: Callable[..., object] | None = None,
    log: Callable[[str], None] | None = None,
) -> ReverseReading | None:
    """Gemini second call: rewrite every beat. Text only — the video
    already authored the original. After retries, stamp the twist onto
    the original beats rather than failing the whole pass."""
    draft = (prompt or '').strip()
    idea = clean_twist(twist)
    if not draft or not idea:
        return None
    user = TWIST_USER.replace('{twist}', idea).replace('{draft}', draft)
    model = vision_api_model(ENGINE_GEMINI)
    if run is None:
        missing = vision_key_missing(ENGINE_GEMINI)
        if missing:
            logger.warning('Magic-pencil prompt skipped: %s — using fallback', missing)
            return _fallback_reading(draft, idea, model='fallback', log=log, reason=missing)
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
    last_err = 'no usable rewrite'
    for attempt in range(3):
        try:
            output = run(model, input=inputs)
            text = _output_text(output)
            reading = parse_reading(text, model=model)
            if not json_reading_complete(text):
                if log:
                    log(f'twist JSON was truncated — retry {attempt + 1}/3')
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
            reading = apply_prompt_cap(reading)
            refined = (reading.prompt or '').strip()
            if twist_rewrite_ok(draft, refined):
                if not reading.keyword or reading.keyword == DEFAULT_KEYWORD:
                    reading.keyword = clean_keyword(idea.split()[0] if idea else DEFAULT_KEYWORD)
                return reading
            last_err = f'short or missing timestamps ({len(refined)} chars)'
            if log:
                log(f'twist rewrite rejected: {last_err}')
        except Exception as exc:
            last_err = str(exc)[:240]
            logger.warning('Magic-pencil prompt failed (try %s/3): %s', attempt + 1, exc)
            if log:
                log(f'twist rewrite try {attempt + 1}/3 failed: {last_err}')
    return _fallback_reading(draft, idea, model=model, log=log, reason=last_err)


def _fallback_reading(
    draft: str,
    idea: str,
    *,
    model: str,
    log: Callable[[str], None] | None,
    reason: str,
) -> ReverseReading:
    if log:
        log(f'Gemini rewrite missed ({reason}) — stamping the twist onto the original beats')
    logger.warning('Magic-pencil fallback: %s', reason)
    prompt = fallback_twist_prompt(draft, idea)
    return ReverseReading(
        keyword=clean_keyword(idea.split()[0] if idea else DEFAULT_KEYWORD),
        prompt=prompt,
        model=f'{model}+fallback' if model else 'fallback',
        raw='',
        cuts=cuts_from_prompt(prompt),
    )


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


def _frame_fields(frame) -> tuple[str, str, float | None]:
    if isinstance(frame, dict):
        key = str(frame.get('key') or '')
        name = str(frame.get('filename') or '')
        raw_t = frame.get('t')
    else:
        key = str(getattr(frame, 'key', '') or '')
        name = str(getattr(frame, 'filename', '') or '')
        raw_t = getattr(frame, 't', None)
    try:
        t = float(raw_t) if raw_t is not None else None
    except (TypeError, ValueError):
        t = None
    return key, name, t


def pack_frames_zip(frames, *, fetch) -> tuple[bytes, list[str]]:
    """One ZIP Ashok can tap once — download all cut / twist JPEGs."""
    buf = io.BytesIO()
    failed: list[str] = []
    written = 0
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for index, frame in enumerate(frames or [], start=1):
            key, name, t = _frame_fields(frame)
            if not name:
                stamp = f'{t:.2f}s' if t is not None else f'{index:02d}'
                name = f'frame-{index:02d}-{stamp}.jpg'
            name = name.replace('/', '-')
            if not key:
                failed.append(str(index))
                continue
            try:
                data = fetch(key)
            except Exception:
                data = None
            if not data:
                failed.append(name)
                continue
            archive.writestr(name, data)
            written += 1
    if written == 0:
        return b'', failed
    return buf.getvalue(), failed


def twist_video_prompt(twist: str, twisted_prompt: str, *, duration_s: float | None = None) -> str:
    """Motion-transfer brief: keep the source clip's motion, wear the twist."""
    idea = clean_twist(twist)
    story = ' '.join((twisted_prompt or '').split())
    if len(story) > 1600:
        story = story[:1600].rsplit(' ', 1)[0]
    seconds = max(3, min(OMNI_MAX_S, int(round(float(duration_s or 8)))))
    return (
        f'Motion transfer. Keep the source video camera motion, pacing, and cuts '
        f'for the full {seconds}s. Restyle every frame to match the reference stills. '
        f'Twist: {idea}. {story}'
    ).strip()


def omni_input_attempts(
    *,
    prompt: str,
    video_url: str | None,
    frame_urls: list[str],
) -> list[dict]:
    """Richest Gemini Omni motion-transfer payload first, then documented
    Replicate fallbacks (image + last_frame) if extra fields are rejected."""
    first = (frame_urls[0] if frame_urls else '').strip()
    last = (frame_urls[-1] if len(frame_urls) > 1 else '').strip()
    video = (video_url or '').strip()
    attempts: list[dict] = []

    def base(**extra) -> dict:
        payload = {
            'prompt': prompt,
            'resolution': '720p',
            'aspect_ratio': '9:16',
        }
        payload.update(extra)
        return payload

    if video and first:
        motion = {'video': video, 'image': first}
        if last and last != first:
            motion['last_frame'] = last
        attempts.append(base(task='edit', **motion))
        attempts.append(base(**motion))
    if first:
        interp = {'image': first}
        if last and last != first:
            interp['last_frame'] = last
        attempts.append(base(**interp))
    if video and not first:
        attempts.append(base(task='edit', video=video))
        attempts.append(base(video=video))
    return attempts


def _play_url(url: str | None) -> str:
    """Replicate must fetch a streamable MP4, not the Save-As query."""
    text = (url or '').strip()
    if not text:
        return ''
    if text.endswith('?download=1'):
        return text[:-len('?download=1')]
    if '&download=1' in text:
        return text.replace('&download=1', '')
    return text


def render_twist_video(
    *,
    twist: str,
    twisted_prompt: str,
    frames: list,
    video_url: str | None,
    duration_s: float | None,
    prompt_id: int,
    run: Callable[..., object] | None = None,
    log: Callable[[str], None] | None = None,
    store: Callable[..., Path] | None = None,
    key_for: Callable[..., str] | None = None,
    read_output: Callable | None = None,
):
    """Original clip + twisted stills → Gemini Omni MP4. Raises on total miss."""
    from app.prompts import video_creator

    idea = clean_twist(twist)
    frame_urls = []
    for frame in frames or []:
        key, _name, _t = _frame_fields(frame)
        if key:
            frame_urls.append(video_creator.public_url(key))
    video = _play_url(video_url)
    prompt = twist_video_prompt(idea, twisted_prompt, duration_s=duration_s)
    attempts = omni_input_attempts(prompt=prompt, video_url=video or None, frame_urls=frame_urls)
    if not attempts:
        return None
    model = (
        getattr(config, 'PROMPT_TWIST_VIDEO_MODEL', '') or TWIST_VIDEO_MODEL
    ).strip() or TWIST_VIDEO_MODEL
    if run is None:
        token = getattr(config, 'REPLICATE_API_TOKEN', '')
        if not token:
            raise RuntimeError('REPLICATE_API_TOKEN missing in job_engine/.env')
        import replicate

        client = replicate.Client(api_token=token)
        budget_s = float(getattr(config, 'PROMPT_VIDEO_TIMEOUT_S', 900))

        def run(model, input):  # noqa: A001
            return video_creator.replicate_render(
                client, model, input=input, budget_s=budget_s, log=log,
            )

    store = store or video_creator.store_bytes
    key_for = key_for or video_creator.asset_key
    read_output = read_output or video_creator._read_output
    last_err: BaseException | None = None
    for index, inputs in enumerate(attempts, start=1):
        try:
            if log:
                log(f'Omni motion transfer {index}/{len(attempts)} · {model}')
            output = run(model, input=inputs)
            data = read_output(output)
            if not data or len(data) < 1024:
                raise RuntimeError('Omni returned an empty file')
            key = key_for('twvid', prompt_id=prompt_id, suffix='mp4')
            path = store(key, data, content_type='video/mp4')
            return video_creator.RenderResult(
                video_key=key,
                video_path=Path(path) if path else Path(key),
                video_url=video_creator.public_url(key),
                model=model,
            )
        except Exception as exc:
            last_err = exc
            logger.warning('Omni attempt %s failed: %s', index, exc)
            if log:
                log(f'Omni attempt {index} failed: {exc}')
    if last_err is not None:
        raise RuntimeError(str(last_err)[:2000]) from last_err
    return None
