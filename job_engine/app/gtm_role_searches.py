"""GTM role×city hunting searches — aim the browser at the roles we serve.

Live incident (2026-08-19): after the GTM store-gates shipped (allowlisted
roles, Chennai/Bengaluru/Remote only), the tower went EMPTY. Root cause:
company-scoped MNC searches query only the company name, India-wide, 3
pages — LinkedIn returns ~75 arbitrary Entry-tagged jobs per giant and the
store gate rightly rejects nearly all of them. Meanwhile a direct probe
("data analyst", Chennai, Intern/Entry, 7 days) showed live rows at
Barclays, Capgemini, Accenture, Wipro — the jobs exist; the searches never
looked where the roles are.

Fix: dedicated role-group searches aimed at each collection city (and a
remote search via LinkedIn f_WT=2). They carry the sentinel
``target_company = WATCHLIST_ANY``: the insert gate keeps a row when its
company matches ANY watched company (plus the usual allowlisted-title and
collection-city gates), and the AI relevance filter is skipped — precision
comes from deterministic gates, not from where the search pointed.
"""

from __future__ import annotations

from sqlalchemy import select

from app.mnc_watchlist import FRESHER_EXPERIENCE_FILTER, needles
from app.models import SearchConfig
from app.schedule import staggered_daily_cron

# Sentinel target_company meaning "any watched company qualifies".
WATCHLIST_ANY = '*'

# LinkedIn geoIds (verified 2026-08-19): city-scoped search pages are spent
# entirely on the target city instead of an India-wide ranking.
CHENNAI_GEO_ID = '106888327'
BENGALURU_GEO_ID = '90009633'  # Greater Bengaluru Area
INDIA_GEO_ID = '102713980'

# (suffix, geo_id, location_label, work_type_filter)
GTM_LOCATIONS: list[tuple[str, str, str, str | None]] = [
    ('Chennai', CHENNAI_GEO_ID, 'Chennai', None),
    ('Bengaluru', BENGALURU_GEO_ID, 'Bengaluru', None),
    ('Remote', INDIA_GEO_ID, 'Remote (India)', '2'),  # LinkedIn f_WT=2
]

# Role groups built from the GTM allowlist (app/target_roles.py). LinkedIn
# guest search honours quoted phrases + OR. Groups keep the search count
# affordable (~8 groups × 3 locations = 24 thin daily searches) while the
# store gate keeps only exact allowlisted titles.
GTM_ROLE_GROUPS: list[tuple[str, str, str]] = [
    ('Data Analyst', '"data analyst" OR "data analysis"', 'tech_digital'),
    ('BI & Analytics',
     '"business intelligence" OR "bi analyst" OR "analytics engineer" OR "analytics trainee"',
     'tech_digital'),
    ('Data Eng & Ops',
     '"data engineer" OR "data engineering" OR "data operations" OR '
     '"reporting analyst" OR "quantitative analyst"',
     'tech_digital'),
    ('Software Dev',
     '"software developer" OR "software development"',
     'tech_digital'),
    ('QA', '"qa automation" OR "qa testing" OR "quality assurance"', 'tech_digital'),
    ('Support',
     '"cloud support" OR "technical support" OR "customer support"',
     'tech_digital'),
    ('Marketing & Business',
     '"digital marketing" OR "business analyst"',
     'tech_digital'),
    ('Finance Ops Apprentice',
     '"finance trainee" OR "finance intern" OR "operations management" OR apprentice',
     'tech_digital'),
]

GTM_MAX_PAGES = 2
_NAME_PREFIX = 'GTM · '


def is_watchlist_any(target_company: str | None) -> bool:
    return (target_company or '').strip() == WATCHLIST_ANY


def gather_watchlist_needles(db) -> list[str]:
    """Every match needle across all real company-scoped searches."""
    out: list[str] = []
    seen: set[str] = set()
    for cfg in db.execute(select(SearchConfig)).scalars():
        target = (cfg.target_company or '').strip()
        if not target or target == WATCHLIST_ANY:
            continue
        for needle in needles(target):
            low = needle.lower()
            if low not in seen:
                seen.add(low)
                out.append(needle)
    return out


def _config_name(group: str, location_suffix: str) -> str:
    return f'{_NAME_PREFIX}{group} — {location_suffix}'


def seed_gtm_role_searches(db, *, start_hour: int = 4) -> dict[str, int]:
    """Idempotently upsert one search per role group × location.

    Runs before the MNC company stagger (default 04:00 local) so the day's
    first catches are the exact roles the bot serves. Existing GTM configs
    are updated in place (keywords/geo may evolve with the catalogue);
    configs are never deleted here.
    """
    existing = {
        (cfg.name or ''): cfg
        for cfg in db.execute(select(SearchConfig)).scalars()
        if (cfg.name or '').startswith(_NAME_PREFIX)
    }
    created = updated = 0
    index = 0
    for group, keywords, sector in GTM_ROLE_GROUPS:
        for suffix, geo_id, label, work_type in GTM_LOCATIONS:
            name = _config_name(group, suffix)
            cron = staggered_daily_cron(index, start_hour=start_hour, interval_minutes=8)
            cfg = existing.get(name)
            if cfg is None:
                db.add(SearchConfig(
                    name=name,
                    keywords=keywords,
                    geo_id=geo_id,
                    location_label=label,
                    schedule_cron=cron,
                    max_pages=GTM_MAX_PAGES,
                    enabled=True,
                    sector=sector,
                    experience_filter=FRESHER_EXPERIENCE_FILTER,
                    track='fresher',
                    target_company=WATCHLIST_ANY,
                    work_type_filter=work_type,
                ))
                created += 1
            else:
                cfg.keywords = keywords
                cfg.geo_id = geo_id
                cfg.location_label = label
                cfg.schedule_cron = cron
                cfg.max_pages = GTM_MAX_PAGES
                cfg.experience_filter = FRESHER_EXPERIENCE_FILTER
                cfg.track = 'fresher'
                cfg.target_company = WATCHLIST_ANY
                cfg.work_type_filter = work_type
                if not cfg.enabled:
                    cfg.enabled = True
                updated += 1
            index += 1
    db.commit()
    return {'created': created, 'updated': updated}
