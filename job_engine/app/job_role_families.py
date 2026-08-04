"""Shared, strict role-family title matching for jobs and market facts."""

from __future__ import annotations

import re

ROLE_FAMILY_REGEX = {
    'ai_ml': (
        r'(?i)(^|[^a-z])(?:ai/?ml|a\.?i\.?|ml|llm|nlp)([^a-z]|$)|'
        r'artificial\s+intelligence|machine\s+learning|genai|generative\s+ai|'
        r'deep\s+learning|computer\s+vision'
    ),
    'data': r'(?i)(^|[^a-z])(?:data|analytics?|business intelligence|bi developer)([^a-z]|$)',
    'software': (
        r'(?i)(^|[^a-z])(?:software|developer|engineer|programmer|full.?stack|'
        r'backend|frontend)([^a-z]|$)'
    ),
    'cybersecurity': (
        r'(?i)(^|[^a-z])(?:cyber|security|soc|penetration|infosec)([^a-z]|$)'
    ),
    'cloud_devops': (
        r'(?i)(^|[^a-z])(?:cloud|devops|sre|site reliability|platform engineer)([^a-z]|$)'
    ),
    'product': r'(?i)(^|[^a-z])(?:product manager|product owner|product analyst)([^a-z]|$)',
    'design': r'(?i)(^|[^a-z])(?:designer|design|ui/?ux|ux|ui)([^a-z]|$)',
}

ROLE_PATTERNS = {key: re.compile(pattern) for key, pattern in ROLE_FAMILY_REGEX.items()}


def title_matches_role_family(title: str | None, family: str | None) -> bool:
    if not family:
        return True
    pattern = ROLE_PATTERNS.get(family)
    return bool(pattern and pattern.search(re.sub(r'(?i)apprentice', '', title or '')))
