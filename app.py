from pathlib import Path
from urllib.parse import quote
import shutil
import sqlite3
import tempfile

from scrapling.fetchers import StealthyFetcher
import ollama

keywords = 'ai product owner'
url = (
    'https://www.linkedin.com/jobs/search/'
    f'?keywords={quote(keywords)}'
    '&geoId=102713980'
    '&f_TPR=r86400'
)

# Dedicated profile (Chrome blocks --remote-debugging-port on the default profile)
PROFILE_DIR = Path.home() / '.config' / 'google-chrome-linkedin'
SOURCE_PROFILE = Path.home() / '.config' / 'google-chrome'


def _copy_sqlite(src: Path, dst: Path) -> bool:
    """Copy a possibly-locked Chrome SQLite DB safely."""
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_db = Path(tmp) / 'db'
            # Prefer online backup so we can copy while Chrome is open
            try:
                src_conn = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
                dst_conn = sqlite3.connect(tmp_db)
                src_conn.backup(dst_conn)
                dst_conn.close()
                src_conn.close()
            except Exception:
                shutil.copy2(src, tmp_db)
            shutil.copy2(tmp_db, dst)
        return True
    except Exception as exc:
        print(f'Warning: could not copy {src.name}: {exc}')
        return False


def sync_linkedin_session():
    """Pull LinkedIn cookies/session from your real Chrome into the bot profile."""
    src_default = SOURCE_PROFILE / 'Default'
    dst_default = PROFILE_DIR / 'Default'
    dst_default.mkdir(parents=True, exist_ok=True)

    # Local State holds the OS-crypt key used for cookies
    local_state = SOURCE_PROFILE / 'Local State'
    if local_state.exists():
        shutil.copy2(local_state, PROFILE_DIR / 'Local State')

    # Newer Chrome stores cookies under Network/
    copied = False
    for rel in (
        'Network/Cookies',
        'Cookies',
        'Network/Cookies-journal',
        'Cookies-journal',
        'Preferences',
        'Secure Preferences',
    ):
        src = src_default / rel
        if src.exists() and src.is_file():
            if src.name.startswith('Cookies'):
                copied = _copy_sqlite(src, dst_default / rel) or copied
            else:
                (dst_default / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst_default / rel)
                copied = True

    # Local storage helps keep the session warm
    for rel in ('Local Storage', 'Session Storage', 'Sessions'):
        src = src_default / rel
        dst = dst_default / rel
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            try:
                shutil.copytree(src, dst, dirs_exist_ok=True)
                copied = True
            except Exception as exc:
                print(f'Warning: could not copy {rel}: {exc}')

    if copied:
        print('Synced LinkedIn session from your Chrome profile.')
    else:
        print('No Chrome cookies found yet — log into LinkedIn in the window that opens.')


def wait_for_jobs(page):
    print('  …waiting for job cards to render…', flush=True)
    page.wait_for_timeout(5000)
    print('  …page settle done', flush=True)
    return page


def stream_ollama(prompt: str):
    """Stream thinking + answer tokens live, like the ollama CLI."""
    print('\n' + '=' * 60, flush=True)
    print('Asking Ollama (qwen3.5:9b) — streaming thinking + answer…', flush=True)
    print('=' * 60 + '\n', flush=True)

    stream = ollama.chat(
        model='qwen3.5:9b',
        messages=[{'role': 'user', 'content': prompt}],
        stream=True,
        think=True,
    )

    in_thinking = False
    in_answer = False

    for chunk in stream:
        msg = chunk.get('message') or {}
        thinking = msg.get('thinking') or ''
        content = msg.get('content') or ''

        if thinking:
            if not in_thinking:
                print('── thinking ──', flush=True)
                in_thinking = True
            print(thinking, end='', flush=True)

        if content:
            if in_thinking and not in_answer:
                print('\n\n── answer ──', flush=True)
                in_answer = True
            elif not in_answer:
                print('── answer ──', flush=True)
                in_answer = True
            print(content, end='', flush=True)

    print('\n', flush=True)


print('Preparing Chrome profile with your LinkedIn login...', flush=True)
sync_linkedin_session()

print(f'Opening LinkedIn jobs for: {keywords}', flush=True)
print('  …launching Chrome (this can take 15–60s)…', flush=True)
page = StealthyFetcher.fetch(
    url,
    headless=False,
    real_chrome=True,
    user_data_dir=str(PROFILE_DIR),
    network_idle=True,
    timeout=90000,
    wait=4000,
    page_action=wait_for_jobs,
    google_search=False,
)
print('  …page fetched, extracting listings…', flush=True)

cards = page.css(
    '.job-card-container, .jobs-search-results__list-item, '
    'li.scaffold-layout__list-item, .base-card, .job-card-list__entity-lockup'
)
if cards:
    print(f'  …found {len(cards)} job cards', flush=True)
    chunks = []
    for card in cards[:25]:
        chunks.append(' '.join(card.css('::text').getall()))
    text = '\n'.join(chunks)[:8000]
else:
    print('  …no job cards matched; using page text fallback', flush=True)
    text = ' '.join(
        page.css('p::text, li::text, span::text, a::text, h3::text, h2::text').getall()
    )[:8000]

print(f'\nPage URL: {getattr(page, "url", url)}', flush=True)
print(f'Fetched ~{len(text)} chars.', flush=True)

if 'sign in' in text.lower() and 'password' in text.lower():
    raise SystemExit(
        'LinkedIn still shows the login page.\n'
        'In the Chrome window that opened, sign into LinkedIn once, then rerun:\n'
        '  python app.py\n'
        'Your login will be saved in ~/.config/google-chrome-linkedin'
    )

stream_ollama(
    f'Summarize the LinkedIn job search results for "{keywords}". '
    f'List the main job titles, companies, locations, and key themes:\n\n{text}'
)