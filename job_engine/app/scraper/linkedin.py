"""LinkedIn jobs scraper — Scrapling only (StealthySession).

One real browser session per run, human-like random delays between all
navigation actions, page-by-page pagination via the `start` offset,
always restricted to the past 24 hours (f_TPR=r86400).
"""

from dataclasses import dataclass, field
import logging
import random
import threading
import time
from urllib.parse import quote

from scrapling.fetchers import StealthySession

from app import config
from app.scraper.parse import (
    ParsedJob, parse_jobs, parse_results_count, looks_like_login_page,
    detect_linkedin_block,
)
from app.scraper.session import sync_linkedin_session
from app.runtime_settings import get_headless, raise_linkedin_block

logger = logging.getLogger(__name__)

# Same card selectors parse.py extracts from — used to know when results exist
CARD_SELECTOR = (
    '.job-card-container, li.jobs-search-results__list-item, '
    'li.scaffold-layout__list-item, .base-card'
)

# Close buttons of LinkedIn's guest "Sign in to view more jobs" modal,
# cookie banners, restore-pages bubble, and similar overlays that freeze UX
POPUP_DISMISS_SELECTORS = (
    'button.contextual-sign-in-modal__modal-dismiss',
    'button.modal__dismiss',
    '.artdeco-modal__dismiss',
    'button[aria-label="Dismiss"]',
    'button[aria-label="Dismiss sign-in modal"]',
    'button[data-tracking-control-name*="dismiss"]',
    'button[aria-label="Close"]',
    'button.artdeco-toast-item__dismiss',
    '#onetrust-accept-btn-handler',
    'button.msg-overlay-bubble-header__control--close',
)


def dismiss_popups(page) -> bool:
    """Click away any sign-in/overlay modal; fall back to Escape. Returns
    True if a popup was visibly closed."""
    for sel in POPUP_DISMISS_SELECTORS:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(int(random.uniform(600, 1200)))
                return True
        except Exception:
            continue
    # Chrome "Restore pages?" / similar text buttons
    for label in ('Restore pages?', 'Cancel', 'Not now', 'Accept', 'Agree'):
        try:
            btn = page.get_by_role('button', name=label)
            if btn and btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(int(random.uniform(600, 1200)))
                return True
        except Exception:
            continue
    try:
        page.keyboard.press('Escape')
    except Exception:
        pass
    return False


class TransientFetchError(RuntimeError):
    """Page fetch failed in a way that is worth retrying inside the session."""


@dataclass
class PageResult:
    page_num: int
    url: str
    http_status: int | None
    jobs: list[ParsedJob] = field(default_factory=list)


def human_delay() -> float:
    delay = random.uniform(config.MIN_DELAY_S, config.MAX_DELAY_S)
    logger.info('human delay %.1fs', delay)
    time.sleep(delay)
    return delay


def build_search_url(
    keywords: str,
    geo_id: str,
    start: int = 0,
    experience_filter: str | None = None,
) -> str:
    """Build a LinkedIn jobs search URL.

    ``experience_filter`` is LinkedIn ``f_E`` codes, comma-joined:
    1=Internship, 2=Entry level, 3=Associate, 4=Mid-Senior, 5=Director, 6=Executive.
    Fresher track uses ``1,2``. Empty/None omits the filter (Market Signal).
    """
    url = (
        'https://www.linkedin.com/jobs/search/'
        f'?keywords={quote(keywords)}'
        f'&geoId={geo_id}'
        f'&f_TPR={config.TIME_FILTER}'
    )
    filt = (experience_filter or '').strip()
    if filt:
        # LinkedIn expects comma-separated codes URL-encoded (1%2C2)
        url += f'&f_E={quote(filt, safe="")}'
    if start:
        url += f'&start={start}'
    return url


def _fetch_with_heartbeat(engine, url: str, label: str, say) -> tuple[object, float]:
    """Fetch a page with a safety heartbeat. The human-browsing routine logs
    its own progress every 30s; this only fires if something is stalling."""
    done = threading.Event()
    start = time.monotonic()

    def beat():
        while not done.wait(45):
            say(f'Still working on {label}… ({int(time.monotonic() - start)}s elapsed)')

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        response = engine.fetch(url)
    except Exception as exc:
        raise TransientFetchError(str(exc)) from exc
    finally:
        done.set()
    return response, time.monotonic() - start


def _fetch_with_retries(engine, url: str, label: str, say) -> tuple[object, float]:
    """Retry transient fetch failures / 5xx with a short human-scale backoff."""
    attempts = max(1, config.FETCH_RETRIES + 1)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response, took = _fetch_with_heartbeat(engine, url, label, say)
            status = getattr(response, 'status', None)
            if status is not None and status >= 500:
                raise TransientFetchError(f'LinkedIn returned HTTP {status}')
            return response, took
        except TransientFetchError as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            wait = random.uniform(6, 14)
            say(f'{label} fetch failed ({exc}); retrying in {wait:.0f}s '
                f'(attempt {attempt + 1}/{attempts})…')
            time.sleep(wait)
    raise TransientFetchError(f'{label} failed after {attempts} attempts: {last_exc}')


def scrape_search(keywords: str, geo_id: str, max_pages: int,
                  on_page=None, should_continue=None, log=None,
                  run_id: int | None = None,
                  experience_filter: str | None = None) -> list[PageResult]:
    """Scrape a LinkedIn job search, page by page, in one browser session.

    ``on_page(PageResult)`` is called after each page so the caller can
    persist results and request-log entries incrementally.
    ``should_continue()`` is checked before every page; return False to
    stop the run gracefully (used for the admin Stop button).

    Pagination stops as soon as LinkedIn's reported "N results" count is
    covered — no pointless page 2/3 fetches when there are only 11 results
    (LinkedIn pads later pages with recommended/duplicate jobs).

    ``log(message)`` receives human-readable progress lines for the Console.
    """
    def say(msg: str):
        if log:
            log(msg)

    def settle(page):
        """Runs inside the browser after navigation: authentic human browsing.

        Instead of a dead network-idle wait, we spend the same ~90s a real
        reader would on the page — scrolling through cards with pauses,
        re-reading, hovering, idling — then glide back to the top and parse.
        Scrolling also makes LinkedIn lazy-load every card.
        """
        t0 = time.monotonic()
        try:
            page.wait_for_selector(CARD_SELECTOR, timeout=30000)
        except Exception:
            say('No job cards after 30s — could be a login or empty page; reading it as-is.')
            return page

        # Never allow a frozen/idle page — enforce product floor of ~75–105s
        dwell_lo = max(75.0, config.PAGE_DWELL_MIN_S)
        dwell_hi = max(dwell_lo, config.PAGE_DWELL_MAX_S)
        dwell = random.uniform(dwell_lo, dwell_hi)
        say(f'Job cards appeared after {time.monotonic() - t0:.0f}s — '
            f'acting like a human reader for ~{dwell:.0f}s before scraping…')
        deadline = time.monotonic() + dwell
        next_report = time.monotonic() + 30
        next_popup_check = time.monotonic() + 8
        deep_scroll_done = False

        page.wait_for_timeout(int(random.uniform(1000, 2500)))
        if dismiss_popups(page):
            say('Closed a LinkedIn popup.')

        # Park the cursor over the results list so wheel events scroll it
        page.mouse.move(random.randint(350, 550), random.randint(300, 500),
                        steps=random.randint(8, 20))
        try:
            page.mouse.click(random.randint(380, 520), random.randint(320, 480))
            page.wait_for_timeout(int(random.uniform(200, 500)))
        except Exception:
            pass

        while time.monotonic() < deadline:
            roll = random.random()
            if roll < 0.40:
                # Read the next couple of cards
                page.mouse.wheel(0, random.randint(250, 700))
                page.wait_for_timeout(int(random.uniform(1200, 3500)))
            elif roll < 0.55:
                # Scroll back up a little to re-read something
                page.mouse.wheel(0, -random.randint(150, 450))
                page.wait_for_timeout(int(random.uniform(900, 2500)))
            elif roll < 0.72:
                # Wander the cursor / hover over a card
                page.mouse.move(random.randint(250, 900), random.randint(200, 650),
                                steps=random.randint(10, 30))
                page.wait_for_timeout(int(random.uniform(500, 1500)))
            elif roll < 0.82 and not deep_scroll_done:
                # Occasional deeper scroll so LinkedIn lazy-loads more cards
                say('Scrolling deeper so more jobs load…')
                for _ in range(random.randint(3, 6)):
                    page.mouse.wheel(0, random.randint(500, 900))
                    page.wait_for_timeout(int(random.uniform(700, 1600)))
                deep_scroll_done = True
            else:
                # Just read — small mouse jitter so the screen never looks frozen
                page.mouse.move(
                    random.randint(300, 700), random.randint(250, 550),
                    steps=random.randint(4, 12),
                )
                page.wait_for_timeout(int(random.uniform(1500, 4000)))

            if time.monotonic() >= next_popup_check:
                # Popups can appear mid-scroll and freeze the page
                if dismiss_popups(page):
                    say('Closed a popup that appeared while browsing.')
                next_popup_check = time.monotonic() + 8

            if time.monotonic() >= next_report:
                say(f'…still browsing like a human ({int(deadline - time.monotonic())}s left)')
                next_report = time.monotonic() + 30

        say('Done reading — scrolling back to the top to collect the jobs…')
        if dismiss_popups(page):
            say('Closed a popup before collecting jobs.')
        for _ in range(12):
            page.mouse.wheel(0, -random.randint(700, 1100))
            page.wait_for_timeout(int(random.uniform(120, 350)))
        page.keyboard.press('Home')
        page.wait_for_timeout(int(random.uniform(800, 1500)))
        return page

    say('Syncing LinkedIn session from Chrome profile…')
    sync = sync_linkedin_session()
    say(sync.detail)
    if not sync.cookies_ok:
        raise RuntimeError(sync.detail)

    results: list[PageResult] = []
    max_pages = max(1, min(max_pages, config.MAX_PAGES))
    seen_ids: set[str] = set()
    total_results: int | None = None

    session_kwargs = dict(
        headless=get_headless(),
        real_chrome=True,
        user_data_dir=str(config.CHROME_BOT_PROFILE),
        # No network_idle: LinkedIn never stops firing background requests,
        # so waiting for idle just burns the full timeout on every page.
        # settle() waits for the job cards instead and browses like a human.
        network_idle=False,
        timeout=90000,
        wait=1000,
        page_action=settle,
        google_search=False,
    )

    mode = 'hidden (cooler)' if get_headless() else 'VISIBLE window'
    exp_note = (
        f', LinkedIn experience f_E={experience_filter.strip()}'
        if (experience_filter or '').strip() else ', all experience levels'
    )
    say(f'Opening browser for "{keywords}" (past 24h{exp_note}, up to {max_pages} pages) — {mode}…')
    try:
        from app.tower_health import record_event_standalone
        record_event_standalone(
            'browser_open',
            run_id=run_id,
            detail=f'{keywords[:120]} · pages≤{max_pages} · headless={get_headless()}',
        )
    except Exception:
        pass
    with StealthySession(**session_kwargs) as engine:
        for page_num in range(max_pages):
            if should_continue is not None and not should_continue():
                logger.info('stop requested, ending run gracefully')
                say('Stop requested — ending run gracefully.')
                break

            url = build_search_url(
                keywords, geo_id,
                start=page_num * config.PAGE_SIZE,
                experience_filter=experience_filter,
            )
            logger.info('fetching page %s: %s', page_num + 1, url)

            if page_num > 0:
                say(f'Waiting like a human before page {page_num + 1}…')
                waited = human_delay()
                say(f'Waited {waited:.1f}s. Navigating to page {page_num + 1}…')
            else:
                say('Navigating to results page 1…')

            response, took = _fetch_with_retries(engine, url, f'page {page_num + 1}', say)
            status = getattr(response, 'status', None)
            say(f'Page {page_num + 1} loaded in {took:.0f}s (HTTP {status}). Reading job cards…')

            jobs_probe = parse_jobs(response)
            block = detect_linkedin_block(
                response, http_status=status, had_job_cards=bool(jobs_probe),
            )
            if block or looks_like_login_page(response):
                if not block:
                    title, text, html = '', '', ''
                    try:
                        from app.scraper.parse import _page_blobs
                        title, text, html = _page_blobs(response)
                    except Exception:
                        pass
                    block = {
                        'reason': 'LinkedIn showed the login / join wall',
                        'page_title': title,
                        'page_text': text[:4000],
                        'html_excerpt': html[:6000],
                        'http_status': status,
                    }
                raise_linkedin_block(
                    reason=block['reason'],
                    url=url,
                    run_id=run_id,
                    page_title=block.get('page_title', ''),
                    page_text=block.get('page_text', ''),
                    html_excerpt=block.get('html_excerpt', ''),
                    http_status=block.get('http_status'),
                )
                result = PageResult(page_num=page_num + 1, url=url, http_status=status)
                if on_page:
                    on_page(result)
                say(f'LINKEDIN BLOCK — {block["reason"]}')
                raise RuntimeError(
                    f'LINKEDIN_BLOCK: {block["reason"]}. '
                    'Open Chrome, confirm you are logged into LinkedIn, '
                    'then clear the Tower alert and rerun.'
                )

            if total_results is None:
                total_results = parse_results_count(response)
                if total_results is not None:
                    logger.info('LinkedIn reports %s results', total_results)
                    say(f'LinkedIn reports {total_results} result(s) for this search.')

            jobs = jobs_probe
            # LinkedIn repeats cards across pages; only keep unseen ones
            new_jobs = [j for j in jobs if j.linkedin_job_id not in seen_ids]
            seen_ids.update(j.linkedin_job_id for j in new_jobs)

            result = PageResult(page_num=page_num + 1, url=url, http_status=status, jobs=new_jobs)
            results.append(result)
            logger.info('page %s: %s cards, %s new', page_num + 1, len(jobs), len(new_jobs))
            say(f'Page {page_num + 1}: {len(jobs)} cards found, {len(new_jobs)} new.')

            if on_page:
                on_page(result)

            if not new_jobs:
                logger.info('no new jobs on this page, stopping pagination')
                say('No new jobs on this page — stopping pagination.')
                break

            if total_results is not None and len(seen_ids) >= total_results:
                logger.info('covered all %s reported results, stopping', total_results)
                say(f'Covered all {total_results} reported results — done paginating.')
                break

            if total_results is not None and (page_num + 1) * config.PAGE_SIZE >= total_results:
                logger.info('reported results fit in %s page(s), stopping', page_num + 1)
                say(f'All {total_results} results fit in {page_num + 1} page(s) — done paginating.')
                break

    say('Browser closed.')
    return results
