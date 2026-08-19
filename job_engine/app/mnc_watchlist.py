"""MNC-first collection — the company watchlist that drives scraping.

Ashok's base-level pivot (2026-08-14): the niche is graduates chasing the
MNC dream — high pay, big brand, tall buildings, a lifestyle change. Role-
keyword searches hoovered up everything (startups, tiny consultancies,
noise). The new base collects COMPLETE data on the outliers only: a curated,
growing watchlist of giants, one company-scoped fresher search per company.

Mechanics:

- Each watched company gets a ``SearchConfig`` with ``target_company`` set:
  LinkedIn keywords = the quoted company name + f_E=1,2 (Internship/Entry)
  + India geo + past-24h window. At insert, only jobs whose card company
  matches the target are kept (see ``company_matches_target``) — precision
  is guaranteed by the post-filter, and the AI relevance filter is skipped
  entirely (the company match IS the relevance). GTM insert gates
  (2026-08-18) further keep only allowlisted role titles
  (``app/target_roles.py``) in Chennai / Bengaluru / Remote.
- ``target_company`` holds pipe-separated match needles; the FIRST needle
  is the canonical display name. Extra needles absorb LinkedIn's own naming
  drift ("JPMorganChase" vs "JPMorgan Chase & Co.").
- The list grows from Ashok's phone: /addcompany <name> (owner Telegram
  command) → ``add_watch_company`` → immediate first scrape.
- Seeding (``scripts/seed_mnc_watchlist.py``, run on every deploy) upserts
  the catalogue below, puts the old role-keyword searches to sleep
  (disabled, definitions kept — never deleted), and never touches company
  configs added later from Telegram.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from app.models import Company, SearchConfig
from app.schedule import staggered_daily_cron
from app.sectors import infer_sector

FRESHER_EXPERIENCE_FILTER = '1,2'  # LinkedIn f_E: Internship + Entry level
COMPANY_MAX_PAGES = 3  # past-24h window per giant rarely exceeds this
INDIA_GEO_ID = '102713980'
INDIA_LABEL = 'India'

# Curated giants (LinkedIn card names). Entry = match needles, pipe-joined;
# the first needle is the canonical display name. Word-boundary matching —
# "Deloitte" also keeps "Deloitte USI" / "Deloitte Consulting"; "Visa" can
# never keep "Visakha Industries".
MNC_CATALOGUE: list[str] = [
    # —— Consulting / Big-4 / global IT services ——
    'Deloitte',
    'EY',
    'KPMG',
    'PwC',
    'Accenture',
    'Capgemini',
    'Cognizant',
    'IBM',
    'Infosys',
    'Tata Consultancy Services|TCS',
    'Wipro',
    'HCLTech|HCL Technologies',
    'Tech Mahindra',
    'LTIMindtree',
    # —— Product / platform giants ——
    'Google',
    'Microsoft',
    'Amazon',
    'Apple',
    'Meta',
    'Oracle',
    'SAP',
    'Adobe',
    'Salesforce',
    'ServiceNow',
    'Atlassian',
    'Workday',
    'Uber',
    'Walmart',
    'Flipkart',
    'Zoho',
    # —— Chips / hardware / networking ——
    'NVIDIA',
    'Intel',
    'AMD',
    'Qualcomm',
    'Broadcom',
    'Texas Instruments',
    'Micron',
    'Cisco',
    'Dell',
    'Samsung',
    'Ericsson',
    'Nokia',
    # —— Global banks / payments ——
    'JPMorganChase|JPMorgan',
    'Goldman Sachs',
    'Morgan Stanley',
    'Barclays',
    'HSBC',
    'Citi',
    'Wells Fargo',
    'American Express',
    'Mastercard',
    'Visa',
    'PayPal',
    # —— Engineering / industrial MNCs ——
    'Bosch',
    'Siemens',
    'Philips',
    'Honeywell',
    'Airbus',
    'Boeing',
]


def needles(target_company: str) -> list[str]:
    return [n.strip() for n in (target_company or '').split('|') if n.strip()]


def display_name(target_company: str) -> str:
    parts = needles(target_company)
    return parts[0] if parts else ''


def company_matches_target(company_name: str | None, target_company: str) -> bool:
    """Whole-word needle match — the precision gate for company-scoped runs."""
    haystack = (company_name or '').lower()
    if not haystack:
        return False
    for needle in needles(target_company):
        pattern = rf'(?<![a-z0-9]){re.escape(needle.lower())}(?![a-z0-9])'
        if re.search(pattern, haystack):
            return True
    return False


def _config_name(display: str) -> str:
    return f'MNC · {display} — Fresher'


def _existing_company_configs(db) -> tuple[dict[str, SearchConfig], int]:
    """(every lowercase needle → its config, count of company configs) —
    keyed by ALL needles so /addcompany TCS can never duplicate the
    'Tata Consultancy Services|TCS' catalogue entry. GTM sentinel configs
    (target_company '*', app/gtm_role_searches.py) are not companies."""
    by_needle: dict[str, SearchConfig] = {}
    count = 0
    for cfg in db.execute(select(SearchConfig)).scalars():
        target = (cfg.target_company or '').strip()
        if target and target != '*':
            count += 1
            for needle in needles(cfg.target_company):
                by_needle[needle.lower()] = cfg
    return by_needle, count


def _ensure_watched_company(db, display: str) -> Company:
    company = db.execute(
        select(Company).where(Company.name.ilike(display))
    ).scalar_one_or_none()
    if company is None:
        company = Company(name=display, watched=True)
        db.add(company)
    elif not company.watched:
        company.watched = True
    return company


def add_watch_company(
    db,
    raw_name: str,
    *,
    slot_index: int | None = None,
) -> tuple[SearchConfig | None, bool]:
    """Idempotently add one company to the watchlist.

    Returns (config, created). ``created`` False = already watched (config
    returned so the caller can report honestly). Callers commit.
    """
    target = '|'.join(needles(raw_name))
    display = display_name(target)
    if not display:
        return None, False
    by_needle, count = _existing_company_configs(db)
    for needle in needles(target):
        cfg = by_needle.get(needle.lower())
        if cfg is not None:
            if not cfg.enabled:
                cfg.enabled = True
            _ensure_watched_company(db, display_name(cfg.target_company))
            return cfg, False
    index = slot_index if slot_index is not None else count
    cfg = SearchConfig(
        name=_config_name(display),
        keywords=f'"{display}"',
        geo_id=INDIA_GEO_ID,
        location_label=INDIA_LABEL,
        schedule_cron=staggered_daily_cron(index, start_hour=5, interval_minutes=12),
        max_pages=COMPANY_MAX_PAGES,
        enabled=True,
        sector=infer_sector(display, display),
        experience_filter=FRESHER_EXPERIENCE_FILTER,
        track='fresher',
        target_company=target,
    )
    db.add(cfg)
    _ensure_watched_company(db, display)
    return cfg, True


def watchlist_roster(db, *, now=None) -> list[dict]:
    """Full roster for the owner /companies command — every company-scoped
    search with catch counts, never truncated (unlike the boards)."""
    from datetime import datetime, timedelta, timezone

    from app.models import JobMaster

    now = now or datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    rows: list[dict] = []
    for cfg in db.execute(select(SearchConfig)).scalars():
        target = (cfg.target_company or '').strip()
        if not target or target == '*':
            # '*' = GTM role×city hunting search, not a company row.
            continue
        jobs_total = db.query(JobMaster).filter(
            JobMaster.search_config_id == cfg.id
        ).count()
        jobs_24h = db.query(JobMaster).filter(
            JobMaster.search_config_id == cfg.id,
            JobMaster.scraped_at >= day_ago,
        ).count()
        rows.append({
            'company': display_name(target),
            'enabled': bool(cfg.enabled),
            'jobs_total': jobs_total,
            'jobs_24h': jobs_24h,
            'last_run_at': (
                cfg.last_run_at.isoformat() if cfg.last_run_at else None
            ),
        })
    rows.sort(key=lambda r: (-r['jobs_total'], r['company'].lower()))
    return rows


def seed_watchlist(db) -> dict[str, int]:
    """Upsert the curated catalogue and put role-keyword searches to sleep.

    - Company configs NOT in the catalogue (added via /addcompany) are never
      touched — the list only grows.
    - Role-keyword configs (target_company empty) are disabled, not deleted:
      definitions stay recoverable, but the wide net stops collecting.
    """
    created = existing = 0
    for index, entry in enumerate(MNC_CATALOGUE):
        _cfg, was_created = add_watch_company(db, entry, slot_index=index)
        if was_created:
            created += 1
        else:
            existing += 1
    slept = 0
    for cfg in db.execute(select(SearchConfig)).scalars():
        if not (cfg.target_company or '').strip() and cfg.enabled:
            cfg.enabled = False
            slept += 1
    db.commit()
    return {'created': created, 'existing': existing, 'role_searches_slept': slept}
