"""Daily "Set alert" job subscriptions (kanban card 2026-08-07).

Scope, per Ashok: a guest who completes a job search can tap "Set alert" to
be told, about once a day, whenever a NEW job matching that same role
family + city + experience appears. This reuses JobMasterEngine's own
matching functions (_matches_role / _matches_city) and HTTP job source —
never a second, divergent notion of "is this a match". Not a premium
feature: every guest gets this from day one.

Matching key is role_family + city + experience — deliberately NOT the
narrow role_keywords a specific button chose (e.g. "NLP Engineer"), because
a narrow keyword can go quiet for days even though its family has plenty of
openings (same class of gap fixed for live search in telegram_buttons.py).

Auto alerts (Ashok, 2026-08-09): "very few will click on set alert...
why can't we automatically send one alert per day on the guest's last
search". Every completed search now auto-subscribes a daily alert on that
exact search — proactive retention instead of waiting for a tap. Rules that
keep it trustworthy rather than spammy:

- One auto slot per guest: a new search REPLACES the previous auto alert
  (last search wins). Explicit "Set alert" taps are 'manual' and are never
  replaced by a later search.
- Tapping 🔕 on an auto alert is a real opt-out: no future search
  auto-subscribes again until the guest explicitly taps "🔔 Set alert".
- Auto alerts respect the same MAX_ACTIVE_ALERTS cap, same once/UTC-day
  cadence, same sent_job_ids dedupe (seeded from what the guest already
  saw), and the same deterministic job rows — nothing model-authored.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.cities import city_label
from app.telegram_job_search import (
    JobMasterIntent,
    _matches_city,
    _matches_role,
    canonical_link,
    experience_display,
)

MAX_ACTIVE_ALERTS = 3
ALERT_JOB_CAP = 10
CANDIDATE_FETCH_LIMIT = 30

ALERT_HINT = '\n\nTip: tap 👍 if this is useful, or 🔕 below anytime to stop this alert.'

AUTO_OPTOUT_STATE_PREFIX = 'auto_alert_optout:'


def _job_id(job: dict[str, Any]) -> str:
    return str(job.get('linkedin_job_id') or job.get('id') or '').strip()


def is_auto_opted_out(sessions, chat_id: str) -> bool:
    return sessions.get_state(f'{AUTO_OPTOUT_STATE_PREFIX}{chat_id}', '') == '1'


def set_auto_opt_out(sessions, chat_id: str, opted_out: bool) -> None:
    sessions.set_state(f'{AUTO_OPTOUT_STATE_PREFIX}{chat_id}', '1' if opted_out else '0')


def create_or_get_alert(
    sessions,
    chat_id: str,
    *,
    role_family: str,
    role_keywords: list[str] | None,
    role_label: str,
    city: str,
    experience: str = 'fresher',
    seen_ids: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Explicit "🔔 Set alert" tap. Returns (alert_or_None, status) where
    status is 'created' | 'exists' | 'limit'.

    An explicit tap always outranks the auto slot: it re-enables
    auto-subscription for future searches, promotes an identical auto alert
    to 'manual' (so the next search never replaces it), and — at the cap —
    evicts the auto alert to make room rather than refusing the guest's
    explicit ask."""
    set_auto_opt_out(sessions, chat_id, False)
    existing = sessions.find_job_alert(
        chat_id,
        role_family=role_family,
        role_keywords=role_keywords,
        city=city,
        experience=experience,
    )
    if existing is not None:
        if existing.get('source') == 'auto':
            sessions.set_job_alert_source(existing['id'], 'manual')
            existing = dict(existing, source='manual')
        return existing, 'exists'
    if sessions.count_active_job_alerts(chat_id) >= MAX_ACTIVE_ALERTS:
        autos = sessions.list_active_auto_job_alerts(chat_id)
        if not autos:
            return None, 'limit'
        sessions.deactivate_job_alert(autos[0]['id'], chat_id)
    alert = sessions.create_job_alert(
        chat_id,
        role_family=role_family,
        role_keywords=role_keywords or [],
        role_label=role_label,
        city=city,
        experience=experience,
        seen_ids=seen_ids or [],
        source='manual',
    )
    return alert, 'created'


def auto_subscribe_last_search(
    sessions,
    chat_id: str,
    *,
    role_family: str,
    role_keywords: list[str] | None,
    role_label: str,
    city: str,
    experience: str = 'fresher',
    seen_ids: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Silently subscribe the guest's LAST completed search to the daily
    alert dispatch (Ashok, 2026-08-09 — proactive retention). Returns
    (alert_or_None, status): 'created' | 'exists' | 'optout' | 'limit'.

    Last search wins: any previous auto alert is replaced. An identical
    already-active alert (auto or manual) is only re-seeded with what the
    guest just saw so tomorrow's dispatch never re-announces it."""
    if is_auto_opted_out(sessions, chat_id):
        return None, 'optout'
    existing = sessions.find_job_alert(
        chat_id,
        role_family=role_family,
        role_keywords=role_keywords,
        city=city,
        experience=experience,
    )
    if existing is not None:
        if seen_ids:
            sessions.mark_job_alert_sent(existing['id'], list(seen_ids))
        return existing, 'exists'
    for auto_alert in sessions.list_active_auto_job_alerts(chat_id):
        sessions.deactivate_job_alert(auto_alert['id'], chat_id)
    if sessions.count_active_job_alerts(chat_id) >= MAX_ACTIVE_ALERTS:
        return None, 'limit'
    alert = sessions.create_job_alert(
        chat_id,
        role_family=role_family,
        role_keywords=role_keywords or [],
        role_label=role_label,
        city=city,
        experience=experience,
        seen_ids=seen_ids or [],
        source='auto',
    )
    return alert, 'created'


def format_my_alerts(alerts: list[dict[str, Any]]) -> tuple[str, list[list[tuple[str, str]]] | None]:
    if not alerts:
        return (
            'You have no active alerts yet. Search for a role, then tap '
            '"🔔 Set alert" on the results to get new matches daily.',
            None,
        )
    lines = [f'YOUR ALERTS · {len(alerts)}/{MAX_ACTIVE_ALERTS}', '']
    keyboard: list[list[tuple[str, str]]] = []
    for index, alert in enumerate(alerts, 1):
        city_txt = f' in {city_label(alert["city"])}' if alert['city'] else ''
        auto_txt = ' · daily (from your last search)' if alert.get('source') == 'auto' else ''
        lines.append(f"{index}. {alert['role_label']}{city_txt}{auto_txt}")
        keyboard.append([(f'🔕 Stop #{index}', f"alert:off:{alert['id']}")])
    return '\n'.join(lines), keyboard


def _format_alert_jobs(jobs: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, job in enumerate(jobs, 1):
        title = str(job.get('title') or '').strip()[:140]
        company = str(job.get('company') or 'Company not stated').strip()[:80]
        experience = experience_display(job.get('experience_band')).strip()[:40]
        lines.append(f'{index}. {title} — {company} — {experience}\n{canonical_link(job)}')
    return '\n\n'.join(lines)


def format_alert_message(
    role_label: str, city: str, jobs: list[dict[str, Any]], *, source: str = 'manual',
) -> str:
    city_txt = f' in {city_label(city)}' if city else ''
    # An auto alert says WHY the guest is hearing from us — a surprise DM
    # with no context reads as spam; "from your last search" reads as help.
    origin = ' — from your last search' if source == 'auto' else ''
    header = f'🔔 New {role_label} openings{city_txt}{origin}:\n\n'
    return header + _format_alert_jobs(jobs) + ALERT_HINT


def _fetch_candidates(
    api_get: Callable[[str, dict[str, Any] | None], dict | list],
    *,
    role_family: str,
    role_keywords: list[str],
    city: str,
    experience: str,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        'limit': CANDIDATE_FETCH_LIMIT,
        'role_family': role_family,
        'title_terms': ' '.join(role_keywords or []),
    }
    if city:
        params['city'] = city
    if experience == 'fresher':
        params['track'] = 'fresher'
    elif experience:
        params['experience'] = experience
    # Checked-only law (2026-08-14): proactive alerts NEVER carry an
    # unverified job — there is no '-unfiltered' override for alerts.
    params['verified'] = 1
    try:
        data = api_get('/api/jobs', params)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get('items') or [])
    return []


def _new_matches(
    jobs: list[dict[str, Any]],
    intent: JobMasterIntent,
    sent_ids: list[str],
) -> list[dict[str, Any]]:
    sent = set(sent_ids or [])
    out: list[dict[str, Any]] = []
    seen_this_pass: set[str] = set()
    for job in jobs:
        job_id = _job_id(job)
        if not job_id or job_id in sent or job_id in seen_this_pass:
            continue
        if not _matches_role(job, intent) or not _matches_city(job, intent):
            continue
        out.append(job)
        seen_this_pass.add(job_id)
    return out


def dispatch_due_alerts(
    sessions,
    api_get: Callable[[str, dict[str, Any] | None], dict | list],
    send_fn: Callable[[str, str, list[list[tuple[str, str]]] | None], None],
) -> int:
    """Once/day scan: for every active alert, send any genuinely new match.

    A caller (the Telegram bot's background scheduler) is expected to call
    this at most once per UTC day — this function itself does not track
    cadence, keeping it simple to unit test in isolation.
    """
    sent_count = 0
    for alert in sessions.list_active_job_alerts_all():
        intent = JobMasterIntent(
            kind='job_search',
            role_family=alert['role_family'],
            role_keywords=alert['role_keywords'],
            cities=[alert['city']] if alert['city'] else [],
            experience=alert['experience'],
        )
        jobs = _fetch_candidates(
            api_get,
            role_family=alert['role_family'],
            role_keywords=alert['role_keywords'],
            city=alert['city'],
            experience=alert['experience'],
        )
        matches = _new_matches(jobs, intent, alert['sent_job_ids'])[:ALERT_JOB_CAP]
        if not matches:
            continue
        text = format_alert_message(
            alert['role_label'], alert['city'], matches,
            source=alert.get('source', 'manual'),
        )
        keyboard = [[
            ('👍 Like', f"alert:like:{alert['id']}"),
            ('🔕 Stop this alert', f"alert:off:{alert['id']}"),
        ]]
        try:
            send_fn(alert['chat_id'], text, keyboard)
        except Exception:
            continue
        sessions.mark_job_alert_sent(alert['id'], [_job_id(job) for job in matches])
        sent_count += 1
    return sent_count


def should_dispatch_today(sessions, *, state_key: str = 'job_alerts_last_dispatch_date') -> bool:
    today = time.strftime('%Y-%m-%d', time.gmtime())
    return sessions.get_state(state_key, '') != today


def mark_dispatched_today(sessions, *, state_key: str = 'job_alerts_last_dispatch_date') -> None:
    today = time.strftime('%Y-%m-%d', time.gmtime())
    sessions.set_state(state_key, today)
