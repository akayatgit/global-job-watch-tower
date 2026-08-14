"""Partner asset storage — /api/partner/v1/assets/{key} (contract 2026-08-14).

Ashok's ruling (v3, same day): AvatarPitch runs only on Vercel; every file
it needs (Pinterest background mirrors, final rendered reels, render-status
docs) lives on the ThinkPad, uploaded and fetched exclusively through this
API over the Cloudflare tunnel.

Security model:
- PUT is bearer-token gated (same PARTNER_API_TOKEN gate as the rest of
  the partner surface: 503 unset, 401 constant-time mismatch).
- GET is deliberately public — iPhone <video> tags and browsers cannot
  attach Authorization headers to media elements. Keys carry
  client-generated random components so URLs are unguessable, and no
  listing endpoint exists anywhere on this surface.
- Keys are strictly validated (whitelist charset, no '..', no dot-leading
  segments) and the resolved path must stay inside the assets root.
- Retention is the 48h GC timer (scripts/setup_avatarpitch_host.sh) —
  everything here is re-renderable, nothing is precious.
"""

from __future__ import annotations

import mimetypes
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app import config
from app.api.partner import require_partner_token

router = APIRouter(prefix='/api/partner/v1')

KEY_REGEX = re.compile(r'^[a-z0-9][a-z0-9/_.-]{2,180}$')
# Every path segment: starts alnum, then safe chars. Kills '..', '.hidden',
# empty segments ('//') and trailing '/' in one rule.
SEGMENT_REGEX = re.compile(r'^[a-z0-9][a-z0-9_.-]*$')

MAX_ASSET_BYTES = 100 * 1024 * 1024  # Cloudflare tunnel per-request cap
CHUNK = 1024 * 1024

# Internal (never servable: keys cannot start with '.')
META_DIR = '.meta'
TMP_DIR = '.tmp'


def assets_root() -> Path:
    return Path(getattr(config, 'PARTNER_ASSETS_DIR', '/srv/avatarpitch/uploads'))


def _validate_key(key: str) -> str:
    key = (key or '').strip()
    if not KEY_REGEX.match(key):
        raise HTTPException(400, 'invalid asset key')
    for segment in key.split('/'):
        if not SEGMENT_REGEX.match(segment):
            raise HTTPException(400, 'invalid asset key segment')
    return key


def _safe_path(base: Path, key: str) -> Path:
    path = (base / key).resolve()
    if not str(path).startswith(str(base.resolve()) + os.sep):
        raise HTTPException(400, 'invalid asset key')
    return path


def _meta_path(root: Path, key: str) -> Path:
    return root / META_DIR / key


def _public_url(key: str) -> str:
    base = (getattr(config, 'PARTNER_PUBLIC_BASE_URL', '') or '').rstrip('/')
    return f'{base}/api/partner/v1/assets/{key}'


@router.put('/assets/{key:path}', dependencies=[Depends(require_partner_token)])
async def put_asset(key: str, request: Request):
    key = _validate_key(key)
    root = assets_root()
    target = _safe_path(root, key)

    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > MAX_ASSET_BYTES:
        raise HTTPException(413, f'asset exceeds {MAX_ASSET_BYTES} bytes')

    tmp_dir = root / TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = tmp_dir / uuid.uuid4().hex

    size = 0
    try:
        with tmp_file.open('wb') as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_ASSET_BYTES:
                    raise HTTPException(413, f'asset exceeds {MAX_ASSET_BYTES} bytes')
                handle.write(chunk)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_file, target)  # atomic: readers never see half a file
    finally:
        tmp_file.unlink(missing_ok=True)

    content_type = (request.headers.get('content-type') or '').split(';')[0].strip()
    if content_type:
        meta = _meta_path(root, key)
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(content_type, encoding='utf-8')

    return JSONResponse({'ok': True, 'url': _public_url(key), 'size': size})


@router.get('/assets/{key:path}')
def get_asset(key: str):
    """Public by design (see module docstring) — capability-URL model."""
    key = _validate_key(key)
    root = assets_root()
    path = _safe_path(root, key)
    if not path.is_file():
        raise HTTPException(404, 'not found')

    content_type: str | None = None
    meta = _meta_path(root, key)
    if meta.is_file():
        content_type = meta.read_text(encoding='utf-8').strip() or None
    if not content_type:
        content_type = mimetypes.guess_type(key)[0] or 'application/octet-stream'

    # FileResponse (Starlette) handles HTTP Range → 206 for iOS Safari video.
    return FileResponse(
        path,
        media_type=content_type,
        headers={'Cache-Control': 'public, max-age=3600'},
    )
