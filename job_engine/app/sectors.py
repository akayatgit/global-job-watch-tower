"""Critical sector map for Watch Tower searches and jobs.

Ashok’s critical industries (2026-08-02):
  Tech Industry → Artificial Intelligence (AI), Digital technologies
  Manufacturing → Advanced manufacturing
  Healthcare · Green economy · Logistics · Tourism
"""

from __future__ import annotations

# Stable ids stored on SearchConfig.sector / JobMaster.sector
CRITICAL_SECTORS: list[dict[str, str]] = [
    {
        'id': 'tech_ai',
        'industry': 'Tech Industry',
        'name': 'Artificial Intelligence (AI)',
        'label': 'Tech · AI',
    },
    {
        'id': 'tech_digital',
        'industry': 'Tech Industry',
        'name': 'Digital technologies',
        'label': 'Tech · Digital',
    },
    {
        'id': 'manufacturing_advanced',
        'industry': 'Manufacturing',
        'name': 'Advanced manufacturing',
        'label': 'Manufacturing',
    },
    {
        'id': 'healthcare',
        'industry': 'Healthcare',
        'name': 'Healthcare',
        'label': 'Healthcare',
    },
    {
        'id': 'green_economy',
        'industry': 'Green economy',
        'name': 'Green economy',
        'label': 'Green economy',
    },
    {
        'id': 'logistics',
        'industry': 'Logistics',
        'name': 'Logistics',
        'label': 'Logistics',
    },
    {
        'id': 'tourism',
        'industry': 'Tourism',
        'name': 'Tourism',
        'label': 'Tourism',
    },
]

SECTOR_BY_ID = {s['id']: s for s in CRITICAL_SECTORS}
VALID_SECTOR_IDS = set(SECTOR_BY_ID)

# Keyword/name hints → sector (first match wins). Used to re-tag existing searches.
_SECTOR_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ('tech_ai', (
        'ai ', ' ai', 'genai', 'machine learning', 'ml ', 'llm', 'nlp',
        'computer vision', 'prompt', 'agentic', 'applied scientist', 'mlops',
        'data scientist', 'data annotation', 'ai trainer', 'ai/ml', 'ai qa',
    )),
    ('tech_digital', (
        'software', 'developer', 'devops', 'cloud', 'kubernetes', 'sre',
        'platform engineer', 'qa ', 'sdet', 'tester', 'cyber', 'security',
        'soc ', 'grc', 'penetration', 'full stack', 'backend', 'frontend',
        'java', 'python', 'react', 'node', 'android', 'ios', 'flutter',
        'golang', 'c++', '.net', 'data engineer', 'data analyst', 'analytics',
        'etl', 'power bi', 'sql', 'product manager', 'product owner',
        'product analyst', 'ui ux', 'ux ', 'designer', 'rpa', 'salesforce',
        'sap', 'blockchain', 'game', 'embedded', 'iot', 'network',
        'system admin', 'it support', 'helpdesk', 'technical support',
        'digital marketing', 'content writer', 'technical writer',
        'risk and control', 'risk & control', 'risks & controls',
        'compliance', 'audit', 'financial analyst', 'risk analyst',
    )),
    ('manufacturing_advanced', (
        'manufactur', 'production engineer', 'industrial engineer',
        'plant engineer', 'quality engineer manufact',
    )),
    ('healthcare', (
        'healthcare', 'clinical', 'hospital', 'pharma', 'pharmacovigilance',
        'medical', 'nursing', 'biotech',
    )),
    ('green_economy', (
        'sustainab', 'renewable', 'solar', 'esg', 'climate', 'green energy',
        'carbon',
    )),
    ('logistics', (
        'logistics', 'supply chain', 'warehouse', 'procurement', 'freight',
    )),
    ('tourism', (
        'tourism', 'hotel', 'hospitality', 'travel', 'airline cabin',
    )),
]


def infer_sector(name: str = '', keywords: str = '') -> str:
    blob = f'{name} {keywords}'.lower()
    for sector_id, hints in _SECTOR_HINTS:
        if any(h in blob for h in hints):
            return sector_id
    return 'tech_digital'


def sector_label(sector_id: str) -> str:
    meta = SECTOR_BY_ID.get(sector_id)
    if meta:
        return meta['label']
    return sector_id or '—'
