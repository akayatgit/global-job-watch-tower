#!/usr/bin/env python3
"""Watch Tower ↔ Telegram Bot API helpers (no Hermes gateway required).

Reads token from ~/.hermes/.env only. Never prints the token.
"""

from __future__ import annotations

import json
import mimetypes
import re
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV = Path.home() / '.hermes' / '.env'
STATE = Path.home() / '.hermes' / 'watch_tower_telegram.json'
BRIEF = Path('/home/user/Documents/documents/briefs/latest.txt')
ROOT = Path('/home/user/Documents/job_engine')


def _load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV.exists():
        return out
    for ln in ENV.read_text(encoding='utf-8').splitlines():
        if not ln or ln.lstrip().startswith('#') or '=' not in ln:
            continue
        k, v = ln.split('=', 1)
        out[k.strip()] = v.strip()
    return out


def _save_env_keys(updates: dict[str, str]) -> None:
    text = ENV.read_text(encoding='utf-8') if ENV.exists() else ''
    lines = text.splitlines()
    keys = set(updates)
    out = []
    for ln in lines:
        if '=' in ln and not ln.lstrip().startswith('#'):
            k = ln.split('=', 1)[0].strip()
            if k in keys:
                continue
        out.append(ln)
    while out and out[-1].strip() == '':
        out.pop()
    out.append('')
    for k, v in updates.items():
        out.append(f'{k}={v}')
    ENV.write_text('\n'.join(out) + '\n', encoding='utf-8')


def _api(token: str, method: str, data: dict | None = None) -> dict:
    url = f'https://api.telegram.org/bot{token}/{method}'
    body = None
    headers = {}
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def discover_chat(token: str, wait_s: int = 0) -> tuple[str, str] | None:
    """Return (chat_id, user_id) from recent private messages."""
    deadline = time.time() + max(0, wait_s)
    offset = None
    while True:
        params = {'timeout': 20 if wait_s else 0}
        if offset is not None:
            params['offset'] = offset
        try:
            q = urllib.parse.urlencode(params)
            data = _api(token, f'getUpdates?{q}' if not params.get('timeout') else 'getUpdates')
            # use POST-style via get with query for long poll
        except Exception:
            data = {'ok': False}
        if wait_s:
            try:
                url = f'https://api.telegram.org/bot{token}/getUpdates?' + urllib.parse.urlencode(params)
                with urllib.request.urlopen(url, timeout=35) as resp:
                    data = json.loads(resp.read().decode())
            except Exception as e:
                print(f'poll error: {e}', file=sys.stderr)
                data = {'ok': False, 'result': []}
        results = data.get('result') or []
        for upd in results:
            offset = int(upd['update_id']) + 1
            msg = upd.get('message') or upd.get('edited_message') or {}
            chat = msg.get('chat') or {}
            frm = msg.get('from') or {}
            if chat.get('type') == 'private' and chat.get('id'):
                return str(chat['id']), str(frm.get('id') or chat['id'])
        if time.time() >= deadline:
            return None
        if not wait_s:
            return None


def send_text(token: str, chat_id: str, text: str) -> bool:
    # Telegram limit ~4096
    chunks = []
    while text:
        chunks.append(text[:4000])
        text = text[4000:]
    for chunk in chunks:
        r = _api(token, 'sendMessage', {
            'chat_id': chat_id,
            'text': chunk,
            'disable_web_page_preview': 'true',
        })
        if not r.get('ok'):
            print(r, file=sys.stderr)
            return False
    return True


def _multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f'----wt{uuid.uuid4().hex}'
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\n'.encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(value.encode('utf-8'))
        chunks.append(b'\r\n')
    for field_name, path in files:
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        chunks.append(f'--{boundary}\r\n'.encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{path.name}"\r\n'.encode()
        )
        chunks.append(f'Content-Type: {ctype}\r\n\r\n'.encode())
        chunks.append(data)
        chunks.append(b'\r\n')
    chunks.append(f'--{boundary}--\r\n'.encode())
    return b''.join(chunks), f'multipart/form-data; boundary={boundary}'


def send_photo(token: str, chat_id: str, photo: Path, caption: str = '') -> bool:
    """Send one photo. Caption optional — image-only chat uses empty caption."""
    fields = {'chat_id': str(chat_id)}
    if caption:
        fields['caption'] = caption[:1024]
    body, content_type = _multipart(fields, [('photo', photo)])
    url = f'https://api.telegram.org/bot{token}/sendPhoto'
    req = urllib.request.Request(url, data=body, headers={'Content-Type': content_type})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors='replace')
        print(f'sendPhoto HTTP {e.code}: {err[:500]}', file=sys.stderr)
        return False
    if not data.get('ok'):
        print(data, file=sys.stderr)
        return False
    return True


def send_media_group(token: str, chat_id: str, photos: list[Path], caption: str = '') -> bool:
    """Send up to 10 photos as an album. Caption on first slide only."""
    if not photos:
        print('no photos', file=sys.stderr)
        return False
    photos = photos[:10]
    media = []
    files: list[tuple[str, Path]] = []
    for i, path in enumerate(photos):
        attach = f'photo{i}'
        item: dict = {'type': 'photo', 'media': f'attach://{attach}'}
        if i == 0 and caption:
            item['caption'] = caption[:1024]
        media.append(item)
        files.append((attach, path))
    body, content_type = _multipart(
        {'chat_id': str(chat_id), 'media': json.dumps(media)},
        files,
    )
    url = f'https://api.telegram.org/bot{token}/sendMediaGroup'
    req = urllib.request.Request(url, data=body, headers={'Content-Type': content_type})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode(errors='replace')
        print(f'sendMediaGroup HTTP {e.code}: {err[:500]}', file=sys.stderr)
        return False
    if not data.get('ok'):
        print(data, file=sys.stderr)
        return False
    return True


def cmd_send_carousel(topic_msg: str | None = None) -> int:
    """Generate fiery carousel from live tower facts and push album to Telegram."""
    env = _load_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    chat = env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        print('Missing TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL — run bootstrap first', file=sys.stderr)
        return 1

    sys.path.insert(0, str(ROOT))
    from app.carousel_gen import generate_carousel  # noqa: WPS433

    try:
        paths, caption, run_dir = generate_carousel(topic_msg=topic_msg)
    except Exception as e:
        print(f'carousel generate failed: {e}', file=sys.stderr)
        return 1

    ok = send_media_group(token, chat, paths, caption)
    try:
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)
    except Exception:
        pass
    if ok:
        print(f'Carousel sent ({len(paths)} slides) → Telegram')
        return 0
    print('carousel send failed', file=sys.stderr)
    return 1


def cmd_image_chat(user_msg: str) -> int:
    """Telegram image-only chat: Carousel word → pro album; else Tanglish meme photo."""
    env = _load_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    chat = env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        print('Missing TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL', file=sys.stderr)
        return 1

    msg = (user_msg or '').strip()
    if re.search(r'\bcarousel\b', msg, re.I):
        return cmd_send_carousel(topic_msg=msg)

    sys.path.insert(0, str(ROOT))
    from app.telegram_meme import compose_meme  # noqa: WPS433

    try:
        path = compose_meme(msg)
    except Exception as e:
        print(f'meme generate failed: {e}', file=sys.stderr)
        return 1

    ok = send_photo(token, chat, path, caption='')
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    if ok:
        print('IMAGE_SENT')
        return 0
    print('meme send failed', file=sys.stderr)
    return 1


def cmd_bootstrap(wait_s: int = 180) -> int:
    env = _load_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    if not token:
        print('TELEGRAM_BOT_TOKEN missing in ~/.hermes/.env', file=sys.stderr)
        return 1
    me = _api(token, 'getMe')
    if not me.get('ok'):
        print('getMe failed', me, file=sys.stderr)
        return 1
    uname = me['result'].get('username')
    print(f'Bot @{uname} live. Open https://t.me/{uname} and tap Start / send hi…')
    found = discover_chat(token, wait_s=wait_s)
    if not found:
        print('No private chat yet. Open the bot and send /start, then re-run bootstrap.', file=sys.stderr)
        return 2
    chat_id, user_id = found
    _save_env_keys({
        'TELEGRAM_BOT_TOKEN': token,
        'TELEGRAM_ALLOWED_USERS': user_id,
        'TELEGRAM_HOME_CHANNEL': chat_id,
        'TELEGRAM_HOME_CHANNEL_NAME': 'Ashok',
        'TELEGRAM_ALLOW_ALL_USERS': 'false',
    })
    STATE.write_text(json.dumps({
        'chat_id': chat_id, 'user_id': user_id, 'username': uname,
    }, indent=2), encoding='utf-8')
    ok = send_text(token, chat_id,
                   'VIGIL linked.\nDaily hiring briefs will land here.\nAsk me about the tower anytime.')
    print(f'Linked chat_id={chat_id} user_id={user_id} welcome_sent={ok}')
    return 0 if ok else 1


def cmd_send_brief() -> int:
    env = _load_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    chat = env.get('TELEGRAM_HOME_CHANNEL')
    if not token or not chat:
        print('Missing TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL — run bootstrap first', file=sys.stderr)
        return 1
    if not BRIEF.exists():
        # generate
        import subprocess
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name('hermes_daily_brief.py'))],
            check=False,
        )
    text = BRIEF.read_text(encoding='utf-8') if BRIEF.exists() else 'No brief yet.'
    ok = send_text(token, chat, text)
    print('sent' if ok else 'failed')
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ('-h', '--help'):
        print('Usage: telegram_watch_tower.py bootstrap|send-brief|send-carousel|image-chat <msg>')
        return 0
    if argv[0] == 'bootstrap':
        wait = int(argv[1]) if len(argv) > 1 else 180
        return cmd_bootstrap(wait)
    if argv[0] == 'send-brief':
        return cmd_send_brief()
    if argv[0] == 'send-carousel':
        topic = ' '.join(argv[1:]).strip() or None
        return cmd_send_carousel(topic_msg=topic)
    if argv[0] == 'image-chat':
        msg = ' '.join(argv[1:]).strip()
        if not msg and not sys.stdin.isatty():
            msg = sys.stdin.read().strip()
        if not msg:
            print('image-chat needs a message', file=sys.stderr)
            return 2
        return cmd_image_chat(msg)
    print('unknown command', argv[0], file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
