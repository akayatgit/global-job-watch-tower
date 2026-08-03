"""Experience band filters for fresher-first Watch Tower insights.

UI chips (human labels) map to stored ``jobs_master.experience_band`` values.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement

from app.models import JobMaster

# Chip catalogue — id stored in vigil.experience / query param
EXPERIENCE_OPTIONS: list[dict[str, str]] = [
    {'id': '', 'label': 'All experience'},
    {'id': 'fresher', 'label': 'Fresher'},
    {'id': '1-2', 'label': '1–2'},
    {'id': '3-5', 'label': '3–5'},
    {'id': '6-8', 'label': '6–8'},
    {'id': '9-12', 'label': '9–12'},
    {'id': '13plus', 'label': '13+'},
]

EXPERIENCE_BY_ID = {o['id']: o for o in EXPERIENCE_OPTIONS if o['id']}
VALID_EXPERIENCE_IDS = set(EXPERIENCE_BY_ID)

# Canonical stored labels (new enrich path)
BAND_FRESHER = 'Fresher'
BAND_1_2 = '1-2 years'
BAND_3_5 = '3-5 years'
BAND_6_8 = '6-8 years'
BAND_9_12 = '9-12 years'
BAND_13_PLUS = '13+ years'

# Filter id → stored band strings (includes legacy labels from earlier enrich)
FILTER_TO_BANDS: dict[str, tuple[str, ...]] = {
    'fresher': (BAND_FRESHER, '0-1 years'),
    '1-2': (BAND_1_2, '1-3 years'),
    '3-5': (BAND_3_5,),
    '6-8': (BAND_6_8, '5-8 years'),
    '9-12': (BAND_9_12, '8-12 years'),
    '13plus': (BAND_13_PLUS, '12+ years'),
}


def experience_options() -> list[dict[str, str]]:
    return list(EXPERIENCE_OPTIONS)


def normalize_experience(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower().replace(' ', '').replace('–', '-').replace('—', '-')
    aliases = {
        'fresher': 'fresher',
        '0-1': 'fresher',
        '0-1years': 'fresher',
        '1-2': '1-2',
        '1-2years': '1-2',
        '3-5': '3-5',
        '3-5years': '3-5',
        '6-8': '6-8',
        '6-8years': '6-8',
        '9-12': '9-12',
        '9-12years': '9-12',
        '13+': '13plus',
        '13plus': '13plus',
        '13+years': '13plus',
    }
    eid = aliases.get(key)
    if eid in VALID_EXPERIENCE_IDS:
        return eid
    return None


def bands_for_filter(experience: str | None) -> tuple[str, ...] | None:
    eid = normalize_experience(experience)
    if not eid:
        return None
    return FILTER_TO_BANDS.get(eid)


def experience_clause(experience: str | None) -> ColumnElement | None:
    """SQLAlchemy WHERE fragment for JobMaster.experience_band, or None."""
    bands = bands_for_filter(experience)
    if not bands:
        return None
    return JobMaster.experience_band.in_(bands)


def experience_label(experience: str | None) -> str:
    eid = normalize_experience(experience)
    if not eid:
        return 'All experience'
    return EXPERIENCE_BY_ID.get(eid, {}).get('label', eid)
