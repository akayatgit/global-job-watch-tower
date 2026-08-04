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
MAX_FETCH = 1000
ALLOWED_WINDOWS = {0, 1, 2, 4, 7, 14, 30}

LINKEDIN_ID_RE = re.compile(r'/jobs/view/(?:[^/?#]*-)?(\d{6,})(?:[/?#]|$)', re.I)
MORE_RE = re.compile(r'^\s*(?:more|next|show\s+more|more\s+jobs|next\s+10)\s*[.!?]*\s*$', re.I)
RESET_RE = re.compile(r'^\s*(?:/new|/reset|/clear|new|reset|clear)\s*$', re.I)

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
    window_days: int = 7


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


def _fallback_intent(text: str) -> JobMasterIntent:
    low = (text or '').lower()
    cities = _extract_cities(low)
    experience = ''
    if re.search(r'\b(?:fresher|freshers|fresh graduate|graduate|entry.?level|intern(?:ship)?)\b', low):
        experience = 'fresher'
    else:
        range_match = re.search(
            r'\b(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*(?:years?|yrs?)?\b',
            low,
        )
        single_match = re.search(r'\b(\d{1,2})\+?\s*(?:years?|yrs?)\b', low)
        if range_match:
            low_years = min(int(range_match.group(1)), int(range_match.group(2)))
            high_years = max(int(range_match.group(1)), int(range_match.group(2)))
            if high_years <= 1:
                experience = 'fresher'
                years = -1
            elif low_years <= 1 and high_years <= 3:
                experience = '1-2'
                years = -1
            else:
                years = high_years
        elif single_match:
            years = int(single_match.group(1))
        else:
            years = -1
        if 0 <= years <= 1:
            experience = 'fresher'
        elif years == 2:
            experience = '1-2'
        elif 3 <= years <= 5:
            experience = '3-5'
        elif 6 <= years <= 8:
            experience = '6-8'
        elif 9 <= years <= 12:
            experience = '9-12'
        elif years >= 13:
            experience = '13plus'

    role_family = ''
    if re.search(
        r'(?i)(?:\bai\b|\bml\b|artificial intelligence|machin(?:e)?\s+learn(?:ing)?|genai|llm)',
        low,
    ):
        role_family = 'ai_ml'
    elif re.search(r'\b(?:data science|data scientist|data analyst|analytics)\b', low):
        role_family = 'data'
    elif re.search(r'\b(?:cyber|security|soc|infosec)\b', low):
        role_family = 'cybersecurity'
    elif re.search(r'\b(?:cloud|devops|sre)\b', low):
        role_family = 'cloud_devops'
    elif re.search(r'\b(?:software|developer|engineer|full.?stack|backend|frontend)\b', low):
        role_family = 'software'

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
        return reply

    def _job_reply(
        self,
        intent: JobMasterIntent,
        *,
        seen_ids: list[str],
    ) -> tuple[str, list[str]]:
        params: dict[str, Any] = {'limit': MAX_FETCH}
        if intent.cities:
            params['city'] = intent.cities[0]
        if intent.experience == 'fresher':
            params['track'] = 'fresher'
        elif intent.experience:
            params['experience'] = intent.experience
        data = self.api_get('/api/jobs', params)
        rows = data if isinstance(data, list) else []
        valid: list[dict[str, Any]] = []
        prior_seen = set(seen_ids)
        fetched_seen: set[str] = set()
        for job in rows:
            link = canonical_link(job)
            title = str(job.get('title') or '').strip()
            company = str(job.get('company') or '').strip()
            if not title or not link or not _matches_role(job, intent):
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
