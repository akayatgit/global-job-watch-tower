"""India city normalization for Watch Tower jobs.

Stable city_key on JobMaster — aliases collapse LinkedIn location variants
(Bengaluru / Bangalore Urban, Gurugram / Gurgaon, etc.).
"""

from __future__ import annotations

CRITICAL_CITIES: list[dict[str, str]] = [
    {'id': 'bengaluru', 'label': 'Bengaluru'},
    {'id': 'hyderabad', 'label': 'Hyderabad'},
    {'id': 'chennai', 'label': 'Chennai'},
    {'id': 'pune', 'label': 'Pune'},
    {'id': 'mumbai', 'label': 'Mumbai'},
    {'id': 'delhi', 'label': 'Delhi'},
    {'id': 'gurugram', 'label': 'Gurugram'},
    {'id': 'noida', 'label': 'Noida'},
    {'id': 'ahmedabad', 'label': 'Ahmedabad'},
    {'id': 'kolkata', 'label': 'Kolkata'},
    {'id': 'remote', 'label': 'Remote'},
    {'id': 'india', 'label': 'India-wide'},
    {'id': 'other', 'label': 'Other'},
]

CITY_BY_ID = {c['id']: c for c in CRITICAL_CITIES}
VALID_CITY_IDS = set(CITY_BY_ID)

# First match wins — more specific metros before country-level.
_CITY_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ('bengaluru', (
        'bengaluru', 'bangalore', 'bengalore',
    )),
    ('hyderabad', (
        'hyderabad', 'secunderabad',
    )),
    ('chennai', (
        'chennai', 'madras',
    )),
    ('pune', (
        'pune', 'pimpri', 'chinchwad',
    )),
    ('mumbai', (
        'mumbai', 'bombay', 'navi mumbai', 'thane',
    )),
    ('gurugram', (
        'gurugram', 'gurgaon',
    )),
    ('noida', (
        'noida', 'greater noida',
    )),
    ('delhi', (
        'new delhi', 'delhi ncr', 'delhi, india', 'delhi india',
        'delhi,',  # "Delhi, India"
    )),
    ('ahmedabad', (
        'ahmedabad', 'amdavad',
    )),
    ('kolkata', (
        'kolkata', 'calcutta',
    )),
]

_REMOTE_HINTS = (
    'remote', 'work from home', 'work-from-home', 'wfh',
    'anywhere in india', 'pan india remote',
)


def normalize_city(location: str | None = None, title: str | None = None) -> str:
    """Map a LinkedIn location (and optional title) to a stable city_key."""
    loc = (location or '').strip()
    blob = f'{loc} {(title or "")}'.lower()
    loc_l = loc.lower().strip()

    if any(h in blob for h in _REMOTE_HINTS):
        # "Bengaluru (Remote)" still counts as that city if a metro is named
        for city_id, hints in _CITY_HINTS:
            if any(h in loc_l for h in hints):
                return city_id
        return 'remote'

    for city_id, hints in _CITY_HINTS:
        if any(h in loc_l for h in hints):
            return city_id

    # Bare "Delhi" (hints need comma/prefix forms to avoid false matches)
    if loc_l == 'delhi' or loc_l.startswith('delhi '):
        return 'delhi'

    # Exact / near-exact country-only labels
    if loc_l in ('india', 'india.', 'pan india', 'pan-india', 'anywhere in india'):
        return 'india'
    if loc_l.replace(' ', '') == 'india':
        return 'india'

    if not loc_l:
        return 'other'
    return 'other'


def city_label(city_id: str | None) -> str:
    if not city_id:
        return '—'
    meta = CITY_BY_ID.get(city_id)
    if meta:
        return meta['label']
    return city_id


def normalize_city_filter(city: str | None) -> str | None:
    """Return a valid city id for API filters, or None (= all cities)."""
    if not city:
        return None
    key = city.strip().lower()
    if key in ('', 'all', '*', 'any'):
        return None
    if key in VALID_CITY_IDS:
        return key
    return None


def city_options() -> list[dict[str, str]]:
    return [
        {'id': '', 'label': 'All cities'},
        *[{'id': c['id'], 'label': c['label']} for c in CRITICAL_CITIES],
    ]


# Metros shown in ranking boards (exclude india/other/remote from "growing cities"
# lists optionally — callers decide).
METRO_CITY_IDS = [
    'bengaluru', 'hyderabad', 'chennai', 'pune', 'mumbai',
    'delhi', 'gurugram', 'noida', 'ahmedabad', 'kolkata',
]
