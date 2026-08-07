"""JobMaster capability #1: grounded jobs and job-market insights.

An LLM may translate messy language into a small, validated intent object.
It never sees or writes job rows, links, counts, or comparisons. Every fact
in the final response comes from Watch Tower HTTP APIs and deterministic
formatters in this module.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app import config
from app.cities import city_label
from app.job_role_families import ROLE_PATTERNS, title_matches_role_family
from app.telegram_sessions import TelegramSessionStore

BASE = 'http://127.0.0.1:8001'
PAGE_SIZE = 10
API_PAGE_SIZE = 200
MAX_SCAN = 10_000
ALLOWED_WINDOWS = {0, 1, 2, 4, 7, 14, 30}

LINKEDIN_ID_RE = re.compile(r'/jobs/view/(?:[^/?#]*-)?(\d{6,})(?:[/?#]|$)', re.I)
MORE_RE = re.compile(r'^\s*(?:more|next|show\s+more|more\s+jobs|next\s+10)\s*[.!?]*\s*$', re.I)
RESET_RE = re.compile(r'^\s*(?:/new|/reset|/clear|new|reset|clear)\s*$', re.I)
# Bare greetings only — a fully specified first message (e.g. "AI jobs in
# Bangalore for fresher") must still return grounded results immediately,
# per Gate 3.0. This never matches inside a longer sentence (fully anchored).
GREETING_RE = re.compile(
    r'^\s*(?:hi+|hello+|hey+|heya|yo+|sup|namaste|vanakkam|'
    r'good\s*(?:morning|afternoon|evening|day))\s*[!.,]*\s*$',
    re.I,
)
SKIP_WORD_RE = re.compile(
    r'^\s*(?:any|no|none|n/?a|nope|skip|anywhere|all|doesn.?t matter|does not matter|'
    r'no preference|not sure|whatever)\s*[!.,]*\s*$',
    re.I,
)
# A returning guest saying "yes" to their recalled profile — zero-friction
# repeat search, no re-asking role/experience/city.
AFFIRMATIVE_RE = re.compile(
    r'^\s*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|please|go ahead|same|same one|'
    r'do that|continue|that one)\s*[!.,]*\s*$',
    re.I,
)
# A returning guest explicitly wanting a different search than the one
# recalled from their stored profile.
DECLINE_RETURN_RE = re.compile(
    r'^\s*(?:no|nope|not that|something else|something new|different|new one|'
    r'new search|fresh)\s*[!.,]*\s*$',
    re.I,
)
ROLE_FAMILY_LABELS = {
    'ai_ml': 'AI/ML',
    'data': 'Data',
    'software': 'Software',
    'cybersecurity': 'Cybersecurity',
    'cloud_devops': 'Cloud/DevOps',
    'product': 'Product',
    'design': 'Design',
}

CITY_ALIASES = {
    'bengaluru': ('bengaluru', 'bangalore', 'bengalore', 'banglore'),
    'hyderabad': ('hyderabad', 'hydrabad', 'secunderabad'),
    'chennai': ('chennai', 'madras'),
    'kerala': ('kerala', 'kochi', 'cochin', 'trivandrum', 'ernakulam'),
    'pune': ('pune',),
    'mumbai': ('mumbai', 'bombay', 'thane'),
    'delhi': ('delhi', 'new delhi', 'delhi ncr'),
    'gurugram': ('gurugram', 'gurgaon'),
    'noida': ('noida', 'greater noida'),
    'ahmedabad': ('ahmedabad', 'amdavad'),
    'kolkata': ('kolkata', 'calcutta'),
    'remote': ('remote', 'work from home', 'wfh'),
    'india': ('india', 'pan india'),
}

FILLER = {
    'a', 'an', 'and', 'any', 'are', 'at', 'available', 'for', 'find', 'fresh',
    'fresher', 'freshers', 'give', 'how', 'in', 'insight', 'insights', 'is',
    'job', 'jobs', 'latest', 'many', 'market', 'me', 'of', 'opening', 'openings',
    'please', 'role', 'roles', 'show', 'space', 'the', 'there', 'today', 'top',
    'total', 'trend', 'trends', 'want', 'which', 'with', 'compare', 'comparison',
    'count', 'currently', 'hiring', 'much', 'vs', 'versus', 'company', 'companies',
    'year', 'years', 'yr', 'yrs',
    # RCA (2026-08-06, live guest test): a bare "yes"/"no"-style word sent at
    # the wrong onboarding stage (e.g. right after a dead-end resets to
    # ask_role, where AFFIRMATIVE_RE/DECLINE_RETURN_RE are never consulted)
    # fell through to here and survived as a literal role_keyword — then
    # _role_label's <=3-char .upper() rule rendered "I don't see verified YES
    # openings today." These words carry no role signal on their own in any
    # stage, so they are always safe to drop before they can leak into a label.
    'yes', 'yeah', 'yep', 'yup', 'sure', 'okay', 'ok', 'no', 'nope', 'go', 'ahead',
    'do', 'that', 'one', 'same', 'continue', 'different', 'something', 'new',
    'else', 'try', 'to',
}
FAMILY_WORDS = {
    'ai', 'ml', 'artificial', 'intelligence', 'machine', 'learning', 'genai',
    'generative', 'llm', 'nlp', 'data', 'science', 'scientist', 'analyst',
    'analytics', 'cyber', 'security', 'soc', 'infosec', 'cloud', 'devops', 'sre',
    'software', 'developer', 'engineer', 'engineering', 'fullstack', 'backend',
    'frontend', 'product', 'manager', 'owner', 'design', 'designer', 'ui', 'ux',
}


def normalize_experience_value(raw: str | None) -> str:
    key = (raw or '').strip().lower().replace(' ', '').replace('–', '-').replace('—', '-')
    aliases = {
        'fresher': 'fresher',
        '0-1': 'fresher',
        '0-1years': 'fresher',
        '1-2': '1-2',
        '1-2years': '1-2',
        '1-3years': '1-2',
        '3-5': '3-5',
        '3-5years': '3-5',
        '6-8': '6-8',
        '6-8years': '6-8',
        '5-8years': '6-8',
        '9-12': '9-12',
        '9-12years': '9-12',
        '8-12years': '9-12',
        '13+': '13plus',
        '13plus': '13plus',
        '13+years': '13plus',
        '12+years': '13plus',
    }
    return aliases.get(key, '')


def experience_display(raw: str | None) -> str:
    value = (raw or '').strip()
    labels = {
        'fresher': 'Fresher',
        '0-1': 'Fresher',
        '0-1 years': 'Fresher',
        '1-2': '1–2 years',
        '1-2 years': '1–2 years',
        '3-5': '3–5 years',
        '3-5 years': '3–5 years',
        '6-8': '6–8 years',
        '6-8 years': '6–8 years',
        '9-12': '9–12 years',
        '9-12 years': '9–12 years',
        '13plus': '13+ years',
        '13+': '13+ years',
        '13+ years': '13+ years',
    }
    return labels.get(value.lower(), value or 'Not stated')


@dataclass
class JobMasterIntent:
    kind: str = 'job_search'  # job_search | insight | help
    role_family: str = ''
    role_keywords: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    experience: str = ''
    metric: str = ''  # count | top_companies | top_roles | compare_cities | trend
    window_days: int = 7  # insight windowing only — see _insight_reply
    # Listing-freshness filter for job_search (button-flow "How fresh should
    # the postings be?" step, 2026-08-07): 0/2/7 days, or None = any time.
    # Deliberately a SEPARATE field from window_days — window_days defaults
    # to 7 and is set on every free-text intent (including job_search ones)
    # by _fallback_intent, so reusing it here would silently start filtering
    # every existing free-text job search to the last 7 days.
    posted_within_days: int | None = None


def _http_get(path: str, params: dict[str, Any] | None = None) -> dict | list:
    url = BASE + path
    clean = {k: v for k, v in (params or {}).items() if v not in (None, '')}
    if clean:
        url += '?' + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _extract_cities(text: str) -> list[str]:
    low = (text or '').lower()
    found: list[tuple[int, str]] = []
    for key, aliases in CITY_ALIASES.items():
        positions = [low.find(alias) for alias in aliases if alias in low]
        if positions:
            found.append((min(positions), key))
    if not found:
        words = re.findall(r'[a-z]+', low)
        all_aliases = [(alias, key) for key, aliases in CITY_ALIASES.items() for alias in aliases]
        for word in words:
            matches = difflib.get_close_matches(word, [a for a, _ in all_aliases], n=1, cutoff=0.82)
            if matches:
                key = next(k for a, k in all_aliases if a == matches[0])
                found.append((low.find(word), key))
                break
    return list(dict.fromkeys(key for _pos, key in sorted(found)))


def _extract_experience(low: str) -> str:
    """Parse a stated experience level out of already-lowercased text."""
    if re.search(r'\b(?:fresher|freshers|fresh graduates?|graduates?|entry.?level|intern(?:ship)?)\b', low):
        return 'fresher'
    range_match = re.search(
        r'\b(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*(?:years?|yrs?)?\b',
        low,
    )
    single_match = re.search(r'\b(\d{1,2})\+?\s*(?:years?|yrs?)\b', low)
    if range_match:
        low_years = min(int(range_match.group(1)), int(range_match.group(2)))
        high_years = max(int(range_match.group(1)), int(range_match.group(2)))
        if high_years <= 1:
            return 'fresher'
        if low_years <= 1 and high_years <= 3:
            return '1-2'
        years = high_years
    elif single_match:
        years = int(single_match.group(1))
    else:
        years = -1
    if 0 <= years <= 1:
        return 'fresher'
    if years == 2:
        return '1-2'
    if 3 <= years <= 5:
        return '3-5'
    if 6 <= years <= 8:
        return '6-8'
    if 9 <= years <= 12:
        return '9-12'
    if years >= 13:
        return '13plus'
    return ''


def _extract_role_family(low: str) -> str:
    """Best-effort role-family bucket out of already-lowercased text."""
    if re.search(
        r'(?i)(?:\bai\b|\bml\b|artificial intelligence|machin(?:e)?\s+learn(?:ing)?|genai|llm)',
        low,
    ):
        return 'ai_ml'
    if re.search(r'\b(?:data science|data scientist|data analyst|analytics)\b', low):
        return 'data'
    if re.search(r'\b(?:cyber|security|soc|infosec)\b', low):
        return 'cybersecurity'
    if re.search(r'\b(?:cloud|devops|sre)\b', low):
        return 'cloud_devops'
    if re.search(r'\b(?:software|developer|engineer|full.?stack|backend|frontend)\b', low):
        return 'software'
    if re.search(r'\b(?:product manager|product owner|product analyst|product)\b', low):
        # A bare "Product" answer (e.g. onboarding's role-step example list
        # says "Product Manager" but people naturally shorten it) still means
        # the Product family — the strict "product manager/owner/analyst"
        # phrase match stays as the JOB-TITLE-side filter (job_role_families.
        # ROLE_FAMILY_REGEX), which is correctly narrow since real postings
        # are never titled bare "Product".
        return 'product'
    if re.search(r'\b(?:designer|design|ui\s*/?\s*ux|\bux\b|\bui\b)\b', low):
        return 'design'
    return ''


def _fallback_intent(text: str) -> JobMasterIntent:
    low = (text or '').lower()
    cities = _extract_cities(low)
    experience = _extract_experience(low)
    role_family = _extract_role_family(low)

    insight = bool(re.search(
        r'\b(?:how many|count|compare|comparison|versus|vs\.?|'
        r'top compan(?:y|ies)|top roles?|trend|market insights?|hiring market|'
        r'which city|growth|grew|growing)\b',
        low,
    ))
    metric = ''
    if insight:
        if len(cities) >= 2 or re.search(r'\b(?:compare|versus|vs\.?)\b', low):
            metric = 'compare_cities'
        elif re.search(r'\btop compan(?:y|ies)\b', low):
            metric = 'top_companies'
        elif re.search(r'\btop roles?\b', low):
            metric = 'top_roles'
        elif re.search(r'\b(?:trend|growth|grew|growing)\b', low):
            metric = 'trend'
        else:
            metric = 'count'

    days = 7
    day_match = re.search(r'\b(1|2|4|7|14|30)\s*(?:d|day|days)\b', low)
    if day_match:
        days = int(day_match.group(1))
    elif '24h' in low or '24 hour' in low:
        days = 0
    elif 'today' in low:
        days = 1

    scrubbed = low
    for aliases in CITY_ALIASES.values():
        for alias in aliases:
            scrubbed = scrubbed.replace(alias, ' ')
    scrubbed = re.sub(
        r'\b\d{1,2}\s*(?:-|–|—|to)\s*\d{1,2}\s*(?:years?|yrs?)?\b',
        ' ',
        scrubbed,
    )
    scrubbed = re.sub(r'\b\d{1,2}\+?\s*(?:years?|yrs?)\b', ' ', scrubbed)
    scrubbed = re.sub(r'\bexperience\b', ' ', scrubbed)
    words = [
        w for w in re.findall(r'[a-z0-9+#.-]+', scrubbed)
        if w not in FILLER and not re.fullmatch(r'\d+(?:-\d+)?', w)
    ]
    if role_family:
        words = [word for word in words if word not in FAMILY_WORDS]
    return JobMasterIntent(
        kind='insight' if insight else 'job_search',
        role_family=role_family,
        role_keywords=words[:5],
        cities=cities[:2],
        experience=experience,
        metric=metric,
        window_days=days,
    )


class IntentInterpreter:
    """Constrained language understanding; output is validated before use."""

    def __init__(self, enabled: bool | None = None):
        if enabled is None:
            enabled = os.getenv('JOBMASTER_LLM_INTENT', 'true').lower() == 'true'
        self.enabled = enabled

    def parse(self, text: str) -> JobMasterIntent:
        fallback = _fallback_intent(text)
        if not self.enabled or not config.OPENAI_API_KEY:
            return fallback
        try:
            from openai import OpenAI

            client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=12)
            response = client.chat.completions.create(
                model=config.OPENAI_BRAIN_MODEL,
                temperature=0,
                response_format={'type': 'json_object'},
                messages=[
                    {
                        'role': 'system',
                        'content': (
                            'Translate the user message into JSON only. You are an intent parser, '
                            'not an answer writer. Keys: kind (job_search|insight|help), '
                            'role_family (ai_ml|data|software|cybersecurity|cloud_devops|product|'
                            'design|empty), role_keywords (array max 5), cities (array max 2 of '
                            'bengaluru|hyderabad|chennai|kerala|pune|mumbai|delhi|gurugram|noida|'
                            'ahmedabad|kolkata|remote|india), experience '
                            '(fresher|1-2|3-5|6-8|9-12|13plus|empty), metric '
                            '(count|top_companies|top_roles|compare_cities|trend|empty), '
                            'window_days (0|1|2|4|7|14|30). Correct spelling and infer meaning. '
                            'Never include jobs, companies, links, counts, advice, or prose.'
                        ),
                    },
                    {'role': 'user', 'content': text[:1200]},
                ],
            )
            raw = json.loads(response.choices[0].message.content or '{}')
            return self._validate(raw, fallback)
        except Exception:
            return fallback

    @staticmethod
    def _validate(raw: dict[str, Any], fallback: JobMasterIntent) -> JobMasterIntent:
        valid_families = set(ROLE_PATTERNS)
        valid_metrics = {'count', 'top_companies', 'top_roles', 'compare_cities', 'trend'}
        kind = raw.get('kind') if raw.get('kind') in {'job_search', 'insight', 'help'} else fallback.kind
        if kind == 'help' and fallback.role_family:
            # RCA (2026-08-05, live test): sending a bare role fragment like
            # "AI ML" got misclassified by the model as kind='help' — a
            # generic assistant-chatter reply instead of a real search —
            # even though the text plainly names a recognized role family.
            # role_keywords is deliberately excluded here: it can pick up
            # ordinary leftover words from genuinely help-ish chatter (e.g.
            # "what can you do"), so only the clean role_family signal is
            # trusted to override the model's own "help" classification.
            kind = fallback.kind
        family = raw.get('role_family') if raw.get('role_family') in valid_families else fallback.role_family
        # City and experience change which facts are returned, so they require
        # deterministic evidence in the user's text. The model may correct
        # intent/role semantics but cannot invent a narrower data scope.
        cities = fallback.cities
        experience = fallback.experience
        keywords = [
            str(w).strip().lower()[:40]
            for w in (raw.get('role_keywords') or [])
            if str(w).strip()
        ][:5]
        if family:
            # Mirror _fallback_intent's FAMILY_WORDS stripping (line ~305) so
            # the LLM path can't re-add a word the family already covers
            # (e.g. family='product' + keyword 'manager') — that duplication
            # was harmless for matching but rendered as "Product Product
            # Manager" in every guest-facing label. See _role_label.
            keywords = [word for word in keywords if word not in FAMILY_WORDS]
        metric = raw.get('metric') if raw.get('metric') in valid_metrics else fallback.metric
        try:
            days = int(raw.get('window_days', fallback.window_days))
        except (TypeError, ValueError):
            days = fallback.window_days
        if days not in ALLOWED_WINDOWS:
            days = fallback.window_days
        return JobMasterIntent(
            kind=kind,
            role_family=family,
            role_keywords=keywords or fallback.role_keywords,
            cities=cities[:2],
            experience=experience,
            metric=metric,
            window_days=days,
        )


def canonical_link(job: dict[str, Any]) -> str:
    job_id = str(job.get('linkedin_job_id') or '').strip()
    if not job_id.isdigit():
        match = LINKEDIN_ID_RE.search(str(job.get('job_url') or ''))
        job_id = match.group(1) if match else ''
    return f'https://www.linkedin.com/jobs/view/{job_id}/' if job_id else ''


def _matches_city(job: dict[str, Any], intent: JobMasterIntent) -> bool:
    if len(intent.cities) < 2:
        return True
    return str(job.get('city_key') or '') in set(intent.cities)


def _matches_role(job: dict[str, Any], intent: JobMasterIntent) -> bool:
    title = str(job.get('title') or '')
    if intent.role_family and not title_matches_role_family(title, intent.role_family):
        return False
    if not intent.role_keywords:
        return True
    low = title.lower()
    matched = sum(1 for word in intent.role_keywords if word in low)
    if matched:
        return True
    phrase = ' '.join(intent.role_keywords)
    return difflib.SequenceMatcher(None, phrase, low).ratio() >= 0.45


def _is_skip_word(text: str) -> bool:
    return bool(SKIP_WORD_RE.match((text or '').strip()))


def _relative_age(timestamp: float) -> str:
    seconds = max(0, int(time.time() - float(timestamp)))
    if seconds < 60:
        return 'Just now'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes}m ago,'
    hours = minutes // 60
    if hours < 24:
        return f'{hours}h ago,'
    days = hours // 24
    return f'{days}d ago,'


def _role_label(role_family: str, role_keywords: list[str]) -> str:
    """RCA (2026-08-06, live guest test): the LLM intent path does not run
    role_keywords through FAMILY_WORDS (only the deterministic fallback
    parser does, see _fallback_intent), so a family of 'product' plus
    LLM-returned keywords ['product', 'manager'] rendered as the duplicated
    "Product Product Manager". Stripping any keyword already implied by the
    family label here — the single place every caller renders a label —
    closes the bug regardless of which parser produced the keywords."""
    family_label = ROLE_FAMILY_LABELS.get(role_family, role_family.replace('_', ' ').title()) if role_family else ''
    family_words = set(family_label.lower().split())
    extra_words = [word for word in (role_keywords or []) if word.lower() not in family_words]
    parts: list[str] = []
    if family_label:
        parts.append(family_label)
    if extra_words:
        parts.append(' '.join(word.upper() if len(word) <= 3 else word.title() for word in extra_words))
    return ' '.join(parts) if parts else 'that role'


def _format_jobs(
    jobs: list[dict[str, Any]],
    *,
    start_number: int,
    has_more: bool,
) -> str:
    if not jobs:
        return 'No more verified jobs match that search right now.' if start_number > 1 else (
            'No verified jobs match that search right now.'
        )
    lines: list[str] = []
    for idx, job in enumerate(jobs, start=start_number):
        title = re.sub(r'\s+', ' ', str(job.get('title') or '')).strip()[:140]
        company = re.sub(
            r'\s+', ' ', str(job.get('company') or 'Company not stated'),
        ).strip()[:80]
        experience = re.sub(
            r'\s+', ' ', experience_display(job.get('experience_band')),
        ).strip()[:40]
        lines.append(f'{idx}. {title} — {company} — {experience}\n{canonical_link(job)}')
    if has_more:
        lines.append('Reply more for 10 more jobs.')
    return '\n\n'.join(lines)


class JobMasterEngine:
    def __init__(
        self,
        *,
        api_get: Callable[[str, dict[str, Any] | None], dict | list] = _http_get,
        interpreter: IntentInterpreter | None = None,
        sessions: TelegramSessionStore | None = None,
    ):
        self.api_get = api_get
        self.interpreter = interpreter or IntentInterpreter()
        self.sessions = sessions or TelegramSessionStore()

    def handle(self, text: str, chat_id: str, *, update_id: int | None = None) -> str:
        raw = (text or '').strip()
        if RESET_RE.match(raw):
            reply = 'Search reset. Send a role, city, or job-market question.'
            self.sessions.clear_onboarding(chat_id)
            self.sessions.apply_result(
                chat_id,
                reply,
                update_id=update_id,
                clear_search=True,
            )
            return reply
        if MORE_RE.match(raw):
            saved = self.sessions.load_search(chat_id)
            if not saved:
                return 'Send a job search first, then reply more.'
            intent_dict, page, seen_ids = saved
            intent = JobMasterIntent(**intent_dict)
            reply, new_ids = self._job_reply(intent, seen_ids=seen_ids)
            self.sessions.apply_result(
                chat_id,
                reply,
                update_id=update_id,
                intent=intent_dict,
                page=page + 1,
                seen_ids=[*seen_ids, *new_ids],
            )
            return reply

        onboarding = self.sessions.load_onboarding(chat_id)
        if onboarding is not None:
            return self._continue_onboarding(onboarding, raw, chat_id, update_id=update_id)
        if GREETING_RE.match(raw):
            return self._start_onboarding(chat_id, update_id=update_id)

        intent = self.interpreter.parse(raw)
        if intent.kind == 'insight':
            reply = self._insight_reply(intent)
            self.sessions.apply_result(chat_id, reply, update_id=update_id)
            return reply
        if intent.kind == 'help':
            reply = 'JobMaster provides verified jobs and live job-market insights.'
            self.sessions.apply_result(chat_id, reply, update_id=update_id)
            return reply

        reply, seen_ids = self._job_reply(intent, seen_ids=[])
        self.sessions.apply_result(
            chat_id,
            reply,
            update_id=update_id,
            intent=asdict(intent),
            page=0,
            seen_ids=seen_ids,
        )
        # Keep the guest-management profile fresh from ANY completed search,
        # not only the guided-onboarding path, so /guestprofile reflects what
        # a returning guest is actually looking for right now.
        self._maybe_save_guest_profile(chat_id, intent)
        return reply

    def _maybe_save_guest_profile(self, chat_id: str, intent: JobMasterIntent) -> None:
        if not intent.role_family and not intent.role_keywords:
            # A stated role is the minimum signal worth remembering; a bare
            # "jobs"-style query never overwrites a guest's real preference.
            return
        self.sessions.save_guest_profile(
            chat_id,
            role_label=_role_label(intent.role_family, intent.role_keywords),
            role_family=intent.role_family,
            role_keywords=intent.role_keywords,
            experience=intent.experience,
            city=intent.cities[0] if intent.cities else '',
        )

    def _job_reply(
        self,
        intent: JobMasterIntent,
        *,
        seen_ids: list[str],
    ) -> tuple[str, list[str]]:
        params: dict[str, Any] = {
            'limit': API_PAGE_SIZE,
            'role_family': intent.role_family,
            'title_terms': ' '.join(intent.role_keywords),
        }
        if len(intent.cities) == 1:
            # A second stated city cannot be pushed down to the API (single
            # value), so it is kept and enforced client-side by _matches_city
            # instead of silently dropped.
            params['city'] = intent.cities[0]
        if intent.experience == 'fresher':
            params['track'] = 'fresher'
        elif intent.experience:
            params['experience'] = intent.experience
        if intent.posted_within_days is not None:
            params['days'] = intent.posted_within_days
        valid: list[dict[str, Any]] = []
        prior_seen = set(seen_ids)
        fetched_seen: set[str] = set()
        offset = 0
        while offset < MAX_SCAN and len(valid) <= PAGE_SIZE:
            data = self.api_get('/api/jobs', {**params, 'offset': offset})
            rows = data if isinstance(data, list) else []
            for job in rows:
                link = canonical_link(job)
                title = str(job.get('title') or '').strip()
                company = str(job.get('company') or '').strip()
                if not title or not link or not _matches_role(job, intent):
                    continue
                if not _matches_city(job, intent):
                    continue
                band = normalize_experience_value(str(job.get('experience_band') or ''))
                if intent.experience == 'fresher' and band and band != 'fresher':
                    continue
                key = str(job.get('linkedin_job_id') or link)
                if key in prior_seen or key in fetched_seen:
                    continue
                fetched_seen.add(key)
                copied = dict(job)
                copied['job_url'] = link
                valid.append(copied)
                if len(valid) > PAGE_SIZE:
                    break
            if len(rows) < API_PAGE_SIZE or len(valid) > PAGE_SIZE:
                break
            offset += len(rows)
        picked = valid[:PAGE_SIZE]
        new_ids = [
            str(job.get('linkedin_job_id') or canonical_link(job))
            for job in picked
        ]
        reply = _format_jobs(
            picked,
            start_number=len(seen_ids) + 1,
            has_more=len(valid) > PAGE_SIZE,
        )
        return reply, new_ids

    def _insight_reply(self, intent: JobMasterIntent) -> str:
        params: dict[str, Any] = {
            'days': intent.window_days,
            'role_family': intent.role_family,
            'title_terms': ' '.join(intent.role_keywords),
        }
        if intent.experience == 'fresher':
            params['track'] = 'fresher'
        elif intent.experience:
            params['experience'] = intent.experience
        scope = city_label(intent.cities[0]) if intent.cities else 'All India'
        if intent.window_days == 0:
            window = 'past 24 hours'
        elif intent.window_days == 1:
            window = 'today'
        else:
            window = f'past {intent.window_days} days'

        if intent.metric == 'compare_cities' and len(intent.cities) >= 2:
            left = self.api_get('/api/jobs/insights', {**params, 'city': intent.cities[0]})
            right = self.api_get('/api/jobs/insights', {**params, 'city': intent.cities[1]})
            if not isinstance(left, dict) or not isinstance(right, dict):
                return 'I could not read that comparison from live Watch Tower data.'
            left_n, right_n = int(left.get('total') or 0), int(right.get('total') or 0)
            return (
                f"{city_label(intent.cities[0])} — {left_n:,} jobs\n"
                f"{city_label(intent.cities[1])} — {right_n:,} jobs\n"
                f"Difference — {abs(left_n - right_n):,} jobs\n"
                f"Window — {window}"
            )

        if intent.metric == 'top_companies':
            data = self.api_get(
                '/api/jobs/insights',
                {**params, 'city': intent.cities[0] if intent.cities else ''},
            )
            companies = (data or {}).get('companies') if isinstance(data, dict) else []
            lines = [
                f"{i}. {row.get('name')} — {int(row.get('n') or 0):,} jobs"
                for i, row in enumerate((companies or [])[:10], 1)
            ]
            return '\n'.join(lines + [f'Window — {window} · {scope}']) if lines else (
                f'No company comparison is available for {scope} in the {window}.'
            )

        if intent.metric == 'top_roles':
            data = self.api_get(
                '/api/jobs/insights',
                {**params, 'city': intent.cities[0] if intent.cities else ''},
            )
            roles = (data or {}).get('roles') if isinstance(data, dict) else []
            lines = [
                f"{i}. {row.get('name')} — {int(row.get('n') or row.get('count') or 0):,} jobs"
                for i, row in enumerate((roles or [])[:10], 1)
            ]
            return '\n'.join(lines + [f'Window — {window} · {scope}']) if lines else (
                f'No role comparison is available for {scope} in the {window}.'
            )

        data = self.api_get(
            '/api/jobs/insights',
            {**params, 'city': intent.cities[0] if intent.cities else ''},
        )
        if not isinstance(data, dict):
            return 'JobMaster could not read that insight from live Watch Tower data.'
        total = int(data.get('total') or 0)
        prior = int(data.get('prior_total') or 0)
        if intent.metric == 'trend':
            direction = 'up' if total > prior else 'down' if total < prior else 'flat'
            return (
                f'{scope} — {total:,} jobs in the {window}\n'
                f'Previous matching window — {prior:,}\n'
                f'Change — {total - prior:+,} ({direction})\n'
                'Source — live Watch Tower'
            )
        return (
            f'{scope} — {total:,} matching jobs in the {window}\n'
            'Source — live Watch Tower'
        )

    # -- Guided onboarding: greet → role → experience → city → results -----

    def _start_onboarding(self, chat_id: str, *, update_id: int | None = None) -> str:
        """A greeting either starts the fresh role→experience→city funnel, or
        — for a returning guest with a remembered profile — recalls it and
        offers a zero-friction repeat instead of asking everything again.
        This recall is a deterministic template over stored structured
        fields; no LLM ever summarizes or invents what a guest searched for.
        """
        profile = self.sessions.get_guest_profile(chat_id)
        if profile and (profile.get('role_family') or profile.get('role_keywords')):
            return self._welcome_back_with_profile(profile, chat_id, update_id=update_id)
        return self._start_fresh_onboarding(chat_id, update_id=update_id)

    def _start_fresh_onboarding(self, chat_id: str, *, update_id: int | None = None) -> str:
        state = {
            'stage': 'ask_role',
            'role_family': '',
            'role_keywords': [],
            'experience': '',
            'experience_known': False,
            'cities': [],
            'city_known': False,
        }
        self.sessions.save_onboarding(chat_id, state)
        reply = (
            "Hi! I'm JobMaster. What job role are you looking for? "
            '(e.g. AI Engineer, Java Developer, Product Manager)'
        )
        self.sessions.apply_result(chat_id, reply, update_id=update_id)
        return reply

    def _welcome_back_with_profile(
        self,
        profile: dict[str, Any],
        chat_id: str,
        *,
        update_id: int | None = None,
    ) -> str:
        state = {
            'stage': 'ask_return_choice',
            'role_family': profile.get('role_family') or '',
            'role_keywords': profile.get('role_keywords') or [],
            'experience': profile.get('experience') or '',
            'experience_known': True,
            'cities': [profile['city']] if profile.get('city') else [],
            'city_known': True,
        }
        self.sessions.save_onboarding(chat_id, state)
        label = _role_label(state['role_family'], state['role_keywords'])
        exp_txt = state['experience'] or 'any experience'
        city_txt = city_label(state['cities'][0]) if state['cities'] else 'any city'
        age = _relative_age(profile['updated_at'])
        reply = (
            f'Welcome back! {age} you were looking for {label} ({exp_txt}) in {city_txt}. '
            "Reply 'yes' for today's openings on that, or tell me a new role."
        )
        self.sessions.apply_result(chat_id, reply, update_id=update_id)
        return reply

    def _continue_onboarding(
        self,
        state: dict[str, Any],
        raw: str,
        chat_id: str,
        *,
        update_id: int | None = None,
    ) -> str:
        stage = state.get('stage')
        note = ''
        if stage == 'ask_role':
            parsed = _fallback_intent(raw)
            if not parsed.role_family and not parsed.role_keywords:
                reply = (
                    "Sorry, I didn't catch a job role — try something like "
                    "'AI Engineer', 'Java Developer', or 'Product Manager'."
                )
                self.sessions.apply_result(chat_id, reply, update_id=update_id)
                return reply
            state['role_family'] = parsed.role_family
            state['role_keywords'] = parsed.role_keywords
            self._absorb_optional_fields(state, parsed)
        elif stage == 'ask_experience':
            if _is_skip_word(raw):
                state['experience'] = ''
            else:
                exp = _extract_experience(raw.lower())
                if exp:
                    state['experience'] = exp
                else:
                    state['experience'] = ''
                    note = (
                        "I couldn't match an experience level from that, so I'll show "
                        'openings across all experience levels. '
                    )
            state['experience_known'] = True
            self._absorb_optional_fields(state, _fallback_intent(raw))
        elif stage == 'ask_city':
            if _is_skip_word(raw):
                state['cities'] = []
            else:
                found = _extract_cities(raw.lower())
                state['cities'] = found[:1]
                if not found:
                    note = (
                        "I couldn't match a city from that, so I'll show openings "
                        'across all cities. '
                    )
            state['city_known'] = True
        elif stage == 'ask_return_choice':
            if AFFIRMATIVE_RE.match(raw):
                return self._finish_onboarding(state, chat_id, update_id=update_id)
            if _is_skip_word(raw) or DECLINE_RETURN_RE.match(raw):
                return self._start_fresh_onboarding(chat_id, update_id=update_id)
            parsed = _fallback_intent(raw)
            if not parsed.role_family and not parsed.role_keywords:
                reply = (
                    "Sorry, I didn't catch that — reply 'yes' for today's openings "
                    'on your last search, or tell me a new job role.'
                )
                self.sessions.apply_result(chat_id, reply, update_id=update_id)
                return reply
            # A different role than the one recalled — treat it as a fresh
            # ask, re-confirming experience/city rather than reusing the old
            # profile's values for an unrelated role.
            state['role_family'] = parsed.role_family
            state['role_keywords'] = parsed.role_keywords
            state['experience'] = ''
            state['experience_known'] = False
            state['cities'] = []
            state['city_known'] = False
            self._absorb_optional_fields(state, parsed)
        else:
            # Corrupt/unknown stage recorded by an older build — fail safe by
            # restarting the flow rather than getting stuck.
            self.sessions.clear_onboarding(chat_id)
            return self._start_fresh_onboarding(chat_id, update_id=update_id)

        return self._progress_onboarding(state, chat_id, update_id=update_id, note=note)

    @staticmethod
    def _absorb_optional_fields(state: dict[str, Any], parsed: JobMasterIntent) -> None:
        """Let an eager answer (e.g. "AI Engineer, fresher, in Chennai") skip
        ahead instead of forcing every question even when already answered."""
        if not state.get('experience_known') and parsed.experience:
            state['experience'] = parsed.experience
            state['experience_known'] = True
        if not state.get('city_known') and parsed.cities:
            state['cities'] = parsed.cities[:1]
            state['city_known'] = True

    def _role_count(self, role_family: str, role_keywords: list[str], city: str = '') -> int:
        data = self.api_get('/api/jobs/insights', {
            'days': 1,  # "today" — matches the product's existing Today window
            'role_family': role_family,
            'title_terms': ' '.join(role_keywords),
            # RCA (2026-08-06, live guest test): "AI jobs in Bangalore" already
            # had the city absorbed into state before this gate ran, but the
            # call silently ignored it — checking "any AI/ML job today,
            # anywhere in India" instead of Bangalore specifically, and then
            # the dead-end reply never even mentioned the city was dropped.
            # Every other insight call in this file passes city (see
            # _insight_reply); this one should too.
            'city': city,
        })
        if not isinstance(data, dict):
            return 0
        return int(data.get('total') or 0)

    def _progress_onboarding(
        self,
        state: dict[str, Any],
        chat_id: str,
        *,
        update_id: int | None = None,
        note: str = '',
    ) -> str:
        if not state.get('experience_known'):
            label = _role_label(state['role_family'], state['role_keywords'])
            city_key = state['cities'][0] if state.get('cities') else ''
            city_txt = f' in {city_label(city_key)}' if city_key else ''
            count = self._role_count(state['role_family'], state['role_keywords'], city_key)
            if count <= 0:
                # A full restart (not just clearing the role) avoids stale
                # experience/city absorbed from this same eager message being
                # silently carried into an unrelated next role attempt.
                state = {
                    'stage': 'ask_role',
                    'role_family': '',
                    'role_keywords': [],
                    'experience': '',
                    'experience_known': False,
                    'cities': [],
                    'city_known': False,
                }
                self.sessions.save_onboarding(chat_id, state)
                reply = (
                    f'{note}I don\u2019t see verified {label} openings today{city_txt}. '
                    'Want to try a different role or city?'
                )
                self.sessions.apply_result(chat_id, reply, update_id=update_id)
                return reply
            state['stage'] = 'ask_experience'
            self.sessions.save_onboarding(chat_id, state)
            plural = 's' if count != 1 else ''
            reply = (
                f'{note}I can get you {count} {label} job posting{plural} today{city_txt}, with links, '
                "but can you share your experience so I can match you better? "
                '(fresher, 1-2, 3-5, 6-8, 9-12, 13+ years, or say \'any\')'
            )
            self.sessions.apply_result(chat_id, reply, update_id=update_id)
            return reply
        if not state.get('city_known'):
            state['stage'] = 'ask_city'
            self.sessions.save_onboarding(chat_id, state)
            reply = f'{note}Do you have a city preference? (e.g. Bengaluru, Chennai, Remote — or say \'any\')'
            self.sessions.apply_result(chat_id, reply, update_id=update_id)
            return reply
        return self._finish_onboarding(state, chat_id, update_id=update_id, note=note)

    def _finish_onboarding(
        self,
        state: dict[str, Any],
        chat_id: str,
        *,
        update_id: int | None = None,
        note: str = '',
    ) -> str:
        intent = JobMasterIntent(
            kind='job_search',
            role_family=state.get('role_family') or '',
            role_keywords=state.get('role_keywords') or [],
            cities=state.get('cities') or [],
            experience=state.get('experience') or '',
        )
        reply, seen_ids = self._job_reply(intent, seen_ids=[])
        no_match = reply in (
            'No verified jobs match that search right now.',
            'No more verified jobs match that search right now.',
        )
        if no_match:
            suggestion = 'Want to try a different role, experience, or city? Just tell me.'
        elif 'Reply more' in reply:
            suggestion = 'Tell me a new role or city anytime.'
        else:
            suggestion = 'Tell me a new role or city anytime, or reply more for more jobs.'
        final_reply = f'{note}{reply}\n\n{suggestion}'.strip()
        self.sessions.clear_onboarding(chat_id)
        self.sessions.apply_result(
            chat_id,
            final_reply,
            update_id=update_id,
            intent=asdict(intent),
            page=0,
            seen_ids=seen_ids,
        )
        self._maybe_save_guest_profile(chat_id, intent)
        return final_reply
