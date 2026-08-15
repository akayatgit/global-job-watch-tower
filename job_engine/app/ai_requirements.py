"""AI reading of stored job descriptions — grounded, never authored.

Ashok (2026-08-15): "Use AI to understand detailed descriptions of jobs."
Regex keeps losing to real employer prose ("candidates having up to one year
of exposure may apply", "only 2025/2026 passouts", years buried inside a
responsibilities paragraph). The local Ollama model READS the stored
``description_text`` and reports what the employer wrote about experience —
but every claim must carry a VERBATIM quote that a deterministic validator
finds in the description before anything is stored. Same VALIDATOR pattern
as boards: the model understands, it never authors facts.

Evidence hierarchy stays intact (soul, 2026-08-15 — rank signals by who can
lie): regex-parsed stated years > AI-read years (quote-grounded, used only
when regex found none) > AI fresher-statement verdict (only matters when no
years are stated at all) > title wording. LinkedIn tags are never evidence.

Costs no browser time: descriptions are already stored by the detail
enrich; this lane is Ollama-only and respects the same thermal gates as
relevance filtering (skip when hot — a NULL ``ai_read_at`` is retried by
the beat backfill later).
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Keep the prompt pure visuals-of-the-task (DIRECTOR prompt hygiene law):
# instructions + data only, no policy text.
PROMPT = """You read ONE job description and report ONLY what the employer \
wrote. Never guess, never infer from the role name, never add anything that \
is not literally in the description.

TITLE: {title}

DESCRIPTION:
{description}

Reply with JSON only:
{{"experience": {{"min_years": <number or null>, "max_years": <number or null>, \
"quote": "<the exact sentence from the description stating the years, or null>"}},
 "fresher_statement": {{"present": <true or false>, \
"quote": "<the exact sentence saying freshers / graduates with no experience are \
welcome, or null>"}},
 "qualifications": ["<degree/qualification exactly as written, e.g. B.Tech>", ...],
 "skills": ["<required skill exactly as written, e.g. SQL>", ...],
 "industry": "<the industry exactly as written, or null>",
 "salary": "<the exact salary text as written, e.g. INR 4,50,000 - 6,00,000 per annum, or null>"}}

Rules:
- Quotes and every list item MUST be copied character-for-character from the description.
- Empty list / null for anything the description does not mention.
- If the description never states years of experience: min_years=null, max_years=null, quote=null.
- fresher_statement.present is true ONLY if the employer explicitly welcomes \
freshers / fresh graduates / people with no experience. A statement that the \
job is NOT for freshers means present=false."""

MAX_DESCRIPTION_CHARS = 8000
MIN_DESCRIPTION_CHARS = 80
MIN_QUOTE_CHARS = 12
EVIDENCE_MAX_CHARS = 400
# Short employer-stated facts (a skill can legitimately be "R" or "Go", but
# 2 chars is the floor so lone letters from bad JSON never slip through).
MIN_ITEM_CHARS = 2
MAX_ITEM_CHARS = 80
MAX_SKILLS = 15
MAX_QUALIFICATIONS = 8
MAX_INDUSTRY_CHARS = 160
MAX_SALARY_CHARS = 200

# A years quote must actually carry a number (digit or word).
NUMBER_ANCHOR_RE = re.compile(
    r'\d|\bzero\b|\bone\b|\btwo\b|\bthree\b|\bfour\b|\bfive\b'
    r'|\bsix\b|\bseven\b|\beight\b|\bnine\b|\bten\b', re.I,
)
# A fresher-statement quote must contain fresher-family wording — the model
# may understand paraphrases, but the quoted sentence itself must be about
# freshers/graduates/experience, not an arbitrary grounded sentence.
FRESHER_ANCHOR_RE = re.compile(
    r'fresher|fresh\s+grad|graduate|no\s+(?:prior\s+|work\s+)?experience'
    r'|zero\s+experience|0\s*(?:years?|yrs?)|pass[\s-]?outs?|batch\s+of'
    r'|campus|trainee|entry[\s-]?level', re.I,
)
# The quoted sentence must not be a NEGATIVE fresher statement.
NEGATED_FRESHER_RE = re.compile(
    r'freshers?\s+(?:need\s+not|should\s+not|must\s+not|cannot|are\s+not|will\s+not)'
    r'|not?\s+(?:for|suitable\s+for|open\s+to|meant\s+for)\s+freshers?'
    r'|no\s+freshers?|except\s+freshers?|other\s+than\s+freshers?'
    r'|freshers?\s+(?:are\s+)?not\s+eligible', re.I,
)
# A salary snippet must carry money evidence — a number plus a currency /
# pay-period word — otherwise the model quoted some unrelated sentence.
SALARY_ANCHOR_RE = re.compile(
    r'(?:₹|\$|€|£|\brs\.?\b|\binr\b|\busd\b|\beur\b|\bgbp\b|\blpa\b|\blakh?s?\b'
    r'|\bcrore\b|\bctc\b|\bsalary\b|\bstipend\b|\bcompensation\b|\bpay\b'
    r'|\bper\s+(?:annum|month|year|hour)\b|\bp\.?a\.?\b|\bk\b)', re.I,
)


@dataclass
class AIReading:
    """A validated, quote-grounded reading of one description."""

    explicit_fresher: bool
    min_years: float | None
    max_years: float | None
    fresher_quote: str | None
    years_quote: str | None
    # Employer-stated facts, each grounded verbatim in the description —
    # empty list / None whenever the employer never mentioned them.
    qualifications: list[str] | None = None
    skills: list[str] | None = None
    industry: str | None = None
    salary_text: str | None = None


def _norm(text: str | None) -> str:
    return re.sub(r'\s+', ' ', (text or '')).strip().lower()


def _quote_grounded(quote: str | None, description_norm: str) -> bool:
    """The one non-negotiable: the quote exists verbatim in the employer's
    own text (whitespace/case-insensitive). A hallucinated quote fails here
    and the claim it carried is discarded."""
    q = _norm(quote)
    return len(q) >= MIN_QUOTE_CHARS and q in description_norm


def _grounded_items(
    values, description_norm: str, *, cap: int,
) -> list[str] | None:
    """Keep only list items that literally appear in the description.
    Hallucinated items are dropped one by one, never the whole list."""
    if not isinstance(values, list):
        return None
    kept: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = ' '.join(value.split())
        norm = _norm(item)
        if not (MIN_ITEM_CHARS <= len(item) <= MAX_ITEM_CHARS):
            continue
        if norm in seen or norm not in description_norm:
            continue
        seen.add(norm)
        kept.append(item)
        if len(kept) >= cap:
            break
    return kept or None


def _as_years(value) -> float | None:
    if value is None:
        return None
    try:
        years = float(value)
    except (TypeError, ValueError):
        return None
    if 0 <= years <= 40:
        return years
    return None


def validate_reading(raw: str, description: str) -> AIReading | None:
    """Deterministic validation of the model's reply. Every claim must be
    grounded; ungrounded claims are dropped individually. Returns None only
    when the reply itself is unusable (bad JSON / wrong shape)."""
    text = (raw or '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    description_norm = _norm(description)

    exp = payload.get('experience') or {}
    min_years = max_years = None
    years_quote = None
    if isinstance(exp, dict):
        quote = exp.get('quote')
        if (
            isinstance(quote, str)
            and _quote_grounded(quote, description_norm)
            and NUMBER_ANCHOR_RE.search(quote)
        ):
            a = _as_years(exp.get('min_years'))
            b = _as_years(exp.get('max_years'))
            if a is not None or b is not None:
                if a is not None and b is not None and a > b:
                    a, b = b, a
                min_years, max_years = a, b
                years_quote = ' '.join(quote.split())[:EVIDENCE_MAX_CHARS]

    fresher = payload.get('fresher_statement') or {}
    explicit_fresher = False
    fresher_quote = None
    if isinstance(fresher, dict) and fresher.get('present') is True:
        quote = fresher.get('quote')
        if (
            isinstance(quote, str)
            and _quote_grounded(quote, description_norm)
            and FRESHER_ANCHOR_RE.search(quote)
            and not NEGATED_FRESHER_RE.search(quote)
        ):
            explicit_fresher = True
            fresher_quote = ' '.join(quote.split())[:EVIDENCE_MAX_CHARS]

    qualifications = _grounded_items(
        payload.get('qualifications'), description_norm, cap=MAX_QUALIFICATIONS,
    )
    skills = _grounded_items(
        payload.get('skills'), description_norm, cap=MAX_SKILLS,
    )

    industry = None
    raw_industry = payload.get('industry')
    if isinstance(raw_industry, str):
        candidate = ' '.join(raw_industry.split())[:MAX_INDUSTRY_CHARS]
        if MIN_ITEM_CHARS <= len(candidate) and _norm(candidate) in description_norm:
            industry = candidate

    salary_text = None
    raw_salary = payload.get('salary')
    if isinstance(raw_salary, str):
        candidate = ' '.join(raw_salary.split())[:MAX_SALARY_CHARS]
        if (
            _norm(candidate) in description_norm
            and re.search(r'\d', candidate)
            and SALARY_ANCHOR_RE.search(candidate)
        ):
            salary_text = candidate

    return AIReading(
        explicit_fresher=explicit_fresher,
        min_years=min_years,
        max_years=max_years,
        fresher_quote=fresher_quote,
        years_quote=years_quote,
        qualifications=qualifications,
        skills=skills,
        industry=industry,
        salary_text=salary_text,
    )


def _chat(prompt: str) -> str:
    import ollama

    from app import config

    response = ollama.chat(
        model=config.OLLAMA_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        format='json',
        think=False,
        options={
            'temperature': 0,
            'num_ctx': 4096,
            'num_predict': 600,
        },
    )
    return response['message']['content']


def read_description(title: str | None, description: str | None) -> AIReading | None:
    """Ollama reads one stored description. Returns None when AI is off,
    the host is too hot, the description is trivial, or the reply never
    validates — callers keep the regex verdict and leave ``ai_read_at``
    NULL so the beat backfill retries later."""
    from app import config, thermal

    if getattr(config, 'AI_REQUIREMENTS_MODE', 'on') == 'off':
        return None
    text = ' '.join((description or '').split())
    if len(text) < MIN_DESCRIPTION_CHARS:
        return None
    if not thermal.ollama_path_open():
        return None

    prompt = PROMPT.format(
        title=(title or 'Unknown')[:200],
        description=text[:MAX_DESCRIPTION_CHARS],
    )
    timeout = min(60.0, float(getattr(config, 'OLLAMA_TIMEOUT_S', 45.0)))
    for attempt in range(2):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                raw = pool.submit(_chat, prompt).result(timeout=timeout)
        except Exception as exc:
            logger.warning('AI description read failed (attempt %s): %s', attempt + 1, exc)
            continue
        reading = validate_reading(raw, text)
        if reading is not None:
            return reading
        logger.warning('AI description reply failed validation (attempt %s)', attempt + 1)
    return None


def apply_reading(job, reading: AIReading) -> list[str]:
    """Merge a validated reading into the job row. Evidence hierarchy:
    regex-parsed stated years are NEVER overwritten (deterministic number
    parsing beats a model); AI-read years fill the gap only when regex found
    none — and they are quote-grounded, so they count as stated years for
    the mandatory fresher law. Returns human-readable notes for the console.
    """
    from app.models.models import utcnow
    from app.scraper.requirements import experience_band

    notes: list[str] = []
    job.ai_read_at = utcnow()
    job.ai_fresher_verdict = reading.explicit_fresher
    job.ai_fresher_evidence = reading.fresher_quote or reading.years_quote
    if reading.explicit_fresher:
        notes.append('AI: explicit fresher statement')
    if job.experience_min_years is None and reading.min_years is not None:
        job.experience_min_years = reading.min_years
        job.experience_max_years = reading.max_years
        job.experience_band = experience_band(reading.min_years, reading.max_years)
        if reading.max_years is not None:
            job.experience_label = (
                f'{reading.min_years:g}-{reading.max_years:g} years (AI-read)'
            )
        else:
            job.experience_label = f'{reading.min_years:g}+ years (AI-read)'
        notes.append(f'AI: stated years {job.experience_label}')

    # Employer-stated facts — only when mentioned, all grounded verbatim.
    if reading.qualifications:
        existing = [d for d in (job.degrees or []) if isinstance(d, str)]
        seen = {d.lower() for d in existing}
        merged = existing + [
            q for q in reading.qualifications if q.lower() not in seen
        ]
        if merged != existing:
            job.degrees = merged[:MAX_QUALIFICATIONS]
            notes.append(f'AI: qualifications {", ".join(reading.qualifications)}')
    if reading.skills and not job.skills:
        job.skills = reading.skills
        notes.append(f'AI: skills {", ".join(reading.skills[:6])}')
    if reading.industry and not job.industry:
        # LinkedIn's own criteria block (enrichment) outranks this fallback —
        # AI fills the gap only when the criteria never said an industry.
        job.industry = reading.industry
        notes.append(f'AI: industry {reading.industry}')
    if reading.salary_text and not job.salary_text:
        job.salary_text = reading.salary_text
        notes.append(f'AI: salary {reading.salary_text}')
    return notes


def pending_ai_read_ids(db, limit: int = 10) -> list[int]:
    """Enriched rows whose stored description has not been AI-read yet —
    newest first (freshest catches reach guests soonest)."""
    from sqlalchemy import select

    from app.models import JobMaster

    rows = db.execute(
        select(JobMaster.id)
        .where(
            JobMaster.description_text.is_not(None),
            JobMaster.requirements_enriched_at.is_not(None),
            JobMaster.ai_read_at.is_(None),
            JobMaster.experience_label.is_distinct_from('enrich_failed'),
        )
        .order_by(JobMaster.id.desc())
        .limit(max(1, min(limit, 30)))
    ).scalars().all()
    return list(rows)
