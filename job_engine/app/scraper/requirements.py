"""Extract structured hiring requirements from LinkedIn job text.

Targets (non-negotiable for Watch Tower employability graph):
  - experience years / band / seniority
  - degrees / qualifications
  - certifications
  - sector / domain experience
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

# --- Experience ---
EXP_RANGE_RE = re.compile(
    r'(?P<a>\d+(?:\.\d+)?)\s*(?:[-–—to]+)\s*(?P<b>\d+(?:\.\d+)?)\s*'
    r'(?:\+?\s*)?(?:years?|yrs?)\b',
    re.I,
)
EXP_MIN_RE = re.compile(
    r'(?:(?:minimum|min\.?|at\s+least|over|more\s+than|'
    r'(?:with|having)\s+)?|^)'
    r'\s*(?P<a>\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b'
    r'(?:\s+of\s+(?:relevant\s+)?experience)?',
    re.I | re.M,
)
EXP_PLUS_RE = re.compile(
    r'(?P<a>\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)\b',
    re.I,
)

SENIORITY_MAP = {
    'internship': 'Internship',
    'entry level': 'Entry level',
    'associate': 'Associate',
    'mid-senior level': 'Mid-Senior level',
    'mid senior level': 'Mid-Senior level',
    'senior': 'Senior',
    'director': 'Director',
    'executive': 'Executive',
    'not applicable': 'Not Applicable',
}

# --- Degrees ---
DEGREE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\bph\.?\s*d\.?\b|\bdoctorate\b', re.I), 'PhD'),
    (re.compile(r'\bm\.?\s*tech\b|\bmtech\b', re.I), 'M.Tech'),
    (re.compile(r'\bm\.?\s*e\.?\b(?!\w)|\bme\b(?=\s+(?:in|degree|computer|electronics))', re.I), 'M.E.'),
    (re.compile(r'\bmba\b|\bmaster(?:\'?s)?\s+of\s+business', re.I), 'MBA'),
    (re.compile(r'\bm\.?\s*s\.?\b(?!\w)|\bmsc\b|\bmaster(?:\'?s)?\s+(?:degree|of\s+science)', re.I), 'Master\'s'),
    (re.compile(r'\bb\.?\s*tech\b|\bbtech\b', re.I), 'B.Tech'),
    (re.compile(r'\bb\.?\s*e\.?\b(?!\w)|\bbe\b(?=\s+(?:in|degree|computer|electronics))', re.I), 'B.E.'),
    (re.compile(r'\bb\.?\s*s\.?\b(?!\w)|\bbsc\b|\bbachelor(?:\'?s)?\s+(?:degree|of\s+science)', re.I), 'Bachelor\'s'),
    (re.compile(r'\bbachelor(?:\'?s)?\b', re.I), 'Bachelor\'s'),
    (re.compile(r'\bmaster(?:\'?s)?\b', re.I), 'Master\'s'),
    (re.compile(r'\bdiploma\b', re.I), 'Diploma'),
]

# --- Certifications (curated + “certified …” capture) ---
CERT_KEYWORDS = [
    ('AWS', re.compile(r'\baws\b(?:\s+certified)?|\bamazon\s+web\s+services\b', re.I)),
    ('Azure', re.compile(r'\bazure\b(?:\s+certified)?|\bmicrosoft\s+azure\b', re.I)),
    ('GCP', re.compile(r'\bgcp\b|\bgoogle\s+cloud\b', re.I)),
    ('PMP', re.compile(r'\bpmp\b|\bproject\s+management\s+professional\b', re.I)),
    ('CISSP', re.compile(r'\bcissp\b', re.I)),
    ('CISA', re.compile(r'\bcisa\b', re.I)),
    ('CISM', re.compile(r'\bcism\b', re.I)),
    ('CEH', re.compile(r'\bceh\b|\bcertified\s+ethical\s+hacker\b', re.I)),
    ('CompTIA Security+', re.compile(r'\bsecurity\+|comptia\s+security', re.I)),
    ('Cisco CCNA', re.compile(r'\bccna\b', re.I)),
    ('Cisco CCNP', re.compile(r'\bccnp\b', re.I)),
    ('Kubernetes CKA', re.compile(r'\bcka\b|\bkubernetes\s+administrator\b', re.I)),
    ('Terraform', re.compile(r'\bterraform\s+associate\b|\bhashicorp\s+terraform\b', re.I)),
    ('ITIL', re.compile(r'\bitil\b', re.I)),
    ('Six Sigma', re.compile(r'\bsix\s+sigma\b|\blean\s+six\s+sigma\b', re.I)),
    ('Salesforce', re.compile(r'\bsalesforce\s+(?:certified|administrator|developer)\b', re.I)),
    ('ISTQB', re.compile(r'\bistqb\b', re.I)),
]
CERT_GENERIC_RE = re.compile(
    r'certified\s+(?:in\s+)?([A-Za-z][A-Za-z0-9+.#/\- ]{2,40})',
    re.I,
)

# --- Domains / sectors of experience ---
DOMAIN_KEYWORDS = [
    ('Banking', re.compile(r'\bbanking\b|\bbfsi\b|\bbank\b', re.I)),
    ('FinTech', re.compile(r'\bfintech\b|\bfinancial\s+services\b|\bpayments?\b', re.I)),
    ('Healthcare', re.compile(r'\bhealthcare\b|\bhealth\s+care\b|\bpharma(?:ceutical)?\b|\bclinical\b', re.I)),
    ('Manufacturing', re.compile(r'\bmanufacturing\b|\bindustrial\s+automation\b|\bot\b|\bplant\b', re.I)),
    ('Retail', re.compile(r'\bretail\b|\be-?commerce\b|\bomnichannel\b', re.I)),
    ('Telecom', re.compile(r'\btelecom(?:munications)?\b|\b5g\b', re.I)),
    ('Automotive', re.compile(r'\bautomotive\b|\boe\s*m\b|\bvehicle\b', re.I)),
    ('Logistics', re.compile(r'\blogistics\b|\bsupply\s+chain\b|\bwarehous', re.I)),
    ('Insurance', re.compile(r'\binsurance\b|\binsurtech\b', re.I)),
    ('Energy', re.compile(r'\benergy\b|\boil\s*(?:&|and)\s*gas\b|\brenewable\b|\bpower\b', re.I)),
    ('Government', re.compile(r'\bgovernment\b|\bpublic\s+sector\b|\bdefence\b|\bdefense\b', re.I)),
    ('SaaS', re.compile(r'\bsaas\b|\bb2b\s+software\b', re.I)),
    ('Cybersecurity', re.compile(r'\bcyber\s*security\b|\binfosec\b|\binformation\s+security\b', re.I)),
    ('AI / ML', re.compile(r'\bmachine\s+learning\b|\bartificial\s+intelligence\b|\bdeep\s+learning\b|\bgenai\b|\bllm\b', re.I)),
    ('Cloud', re.compile(r'\bcloud\s+(?:native|computing|infrastructure|platform)\b', re.I)),
    ('EdTech', re.compile(r'\bedtech\b|\beducation\s+technology\b', re.I)),
    ('Media', re.compile(r'\bmedia\b|\bentertainment\b|\bstreaming\b', re.I)),
    ('Real Estate', re.compile(r'\breal\s+estate\b|\bproptech\b', re.I)),
    ('Travel / Tourism', re.compile(r'\btravel\b|\btourism\b|\bhospitality\b', re.I)),
]


@dataclass
class JobRequirements:
    experience_min_years: float | None = None
    experience_max_years: float | None = None
    experience_label: str | None = None
    experience_band: str | None = None
    seniority_level: str | None = None
    degrees: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    description_text: str | None = None


def experience_band(min_y: float | None, max_y: float | None) -> str | None:
    """Map year range → chip bands: Fresher · 1-2 · 3-5 · 6-8 · 9-12 · 13+."""
    if min_y is None and max_y is None:
        return None
    lo = min_y if min_y is not None else max_y or 0
    hi = max_y if max_y is not None else min_y or 0
    # Graduate / early windows (0–1, 0–2, ≤2) → Fresher
    if hi <= 2.0 and lo <= 1.0:
        return 'Fresher'
    mid = (lo + hi) / 2.0
    if mid < 1.0:
        return 'Fresher'
    if mid < 2.5:
        return '1-2 years'
    if mid < 5.5:
        return '3-5 years'
    if mid < 8.5:
        return '6-8 years'
    if mid < 12.5:
        return '9-12 years'
    return '13+ years'


FRESHER_TEXT_RE = re.compile(
    r'(?:'
    r'\bfreshers?\b|\bfresh\s+graduate\b|\bcampus\s+hire\b|\bcampus\s+recruit\b'
    r'|\bgraduate\s+trainee\b|\bgraduate\s+engineer\b|\bgraduate\s+hire\b'
    r'|\bmanagement\s+trainee\b|\banalyst\s+trainee\b'
    r'|\bno\s+experience\b|\bzero\s+experience\b|\b0\s*(?:years?|yrs?)\b'
    r'|\bentry[\s-]?level\b'
    r')',
    re.I,
)


def _uniq(items: list[str], limit: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        t = ' '.join((raw or '').split()).strip(' .,;:')
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t[:80])
        if len(out) >= limit:
            break
    return out


def extract_experience(text: str) -> tuple[float | None, float | None, str | None]:
    if not text:
        return None, None, None
    m = EXP_RANGE_RE.search(text)
    if m:
        a, b = float(m.group('a')), float(m.group('b'))
        lo, hi = (a, b) if a <= b else (b, a)
        return lo, hi, f'{lo:g}-{hi:g} years'
    m = EXP_PLUS_RE.search(text)
    if m:
        a = float(m.group('a'))
        return a, None, f'{a:g}+ years'
    # Prefer lines that mention experience
    for line in text.splitlines() if '\n' in text else [text]:
        if 'experience' not in line.lower() and 'exp' not in line.lower():
            continue
        m = EXP_MIN_RE.search(line)
        if m:
            a = float(m.group('a'))
            if a <= 40:  # guard against dates / IDs
                return a, None, f'{a:g}+ years'
    m = EXP_MIN_RE.search(text)
    if m:
        a = float(m.group('a'))
        if 0 <= a <= 40:  # allow explicit "0 years"
            return a, None, f'{a:g}+ years' if a > 0 else '0 years'
    return None, None, None


def extract_degrees(text: str) -> list[str]:
    hits: list[str] = []
    for pat, label in DEGREE_PATTERNS:
        if pat.search(text):
            hits.append(label)
    return _uniq(hits, 8)


def extract_certifications(text: str) -> list[str]:
    hits: list[str] = []
    for label, pat in CERT_KEYWORDS:
        if pat.search(text):
            hits.append(label)
    for m in CERT_GENERIC_RE.finditer(text):
        chunk = m.group(1).strip()
        # Drop trailing junk words
        chunk = re.split(r'\b(?:preferred|required|or|and)\b', chunk, maxsplit=1)[0]
        chunk = chunk.strip(' .,;:')
        if len(chunk) >= 3:
            hits.append(chunk.title() if chunk.islower() else chunk)
    return _uniq(hits, 10)


def extract_domains(text: str) -> list[str]:
    hits: list[str] = []
    # Prefer sentences that look like domain experience requirements
    for label, pat in DOMAIN_KEYWORDS:
        if pat.search(text):
            hits.append(label)
    return _uniq(hits, 10)


def normalize_seniority(raw: str | None) -> str | None:
    if not raw:
        return None
    key = ' '.join(raw.lower().split())
    for needle, label in SENIORITY_MAP.items():
        if needle in key:
            return label
    return raw.strip()[:80] or None


def extract_requirements(
    description: str,
    *,
    seniority: str | None = None,
    card_text: str | None = None,
) -> JobRequirements:
    blob = ' '.join(
        p for p in (description or '', card_text or '') if p
    )
    blob = ' '.join(blob.split())
    amin, amax, label = extract_experience(blob)
    band = experience_band(amin, amax)
    # Seniority can imply a band when years missing
    sen = normalize_seniority(seniority)
    if band is None and sen:
        if sen in ('Internship', 'Entry level'):
            band = 'Fresher'
            if amin is None:
                amin, label = 0, sen
        elif sen == 'Associate':
            band = '1-2 years'
        elif sen in ('Mid-Senior level', 'Senior'):
            band = '6-8 years'
        elif sen in ('Director', 'Executive'):
            band = '13+ years'
    # Fresher / campus / graduate language → Fresher when years sparse or ≤2
    if FRESHER_TEXT_RE.search(blob):
        if band is None or (amax is not None and amax <= 2) or (
            amin is not None and amax is None and amin <= 1
        ):
            band = 'Fresher'
            if amin is None:
                amin = 0.0
            if not label:
                label = 'Fresher / graduate'
    return JobRequirements(
        experience_min_years=amin,
        experience_max_years=amax,
        experience_label=label or sen,
        experience_band=band,
        seniority_level=sen,
        degrees=extract_degrees(blob),
        certifications=extract_certifications(blob),
        domains=extract_domains(blob),
        description_text=(description or '')[:20000] or None,
    )
