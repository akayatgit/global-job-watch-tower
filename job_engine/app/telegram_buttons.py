"""Deterministic, button-driven guest flow for JobMaster.

2026-08-06 pivot: Ashok reported the free-text/AI onboarding path was fragile
and confusing for real guests. Rather than parsing natural language, guests
now tap through Family -> Role -> Experience -> Posting window -> City ->
Results using Telegram inline keyboards — no typing required for the
primary path. The posting-window step (2026-08-07: "24hr, 2d, 1w" filter
layer after experience) lets a guest choose how fresh the postings must be
before picking a city.

GTM focus: only Intern and Fresher lead to a live search (Watch Tower's
"fresher" track already covers Internship + Entry-level LinkedIn postings —
see documents/roadmap.md). Every other experience band shows a static
"coming soon" message and collects an email for the waitlist instead of
running (and possibly disappointing on) a search we are not ready to serve.

Free text keeps working exactly as it does today via JobMasterEngine.handle
— this module is additive, not a replacement. See telegram_job_bot.py for
how the two are wired together (callback_query -> this module; everything
else -> the existing engine, unchanged).

Every fact this module ever shows a guest (job counts, titles, companies,
links) is produced by JobMasterEngine's existing, tested, deterministic
formatters (_job_reply / _maybe_save_guest_profile) — this module only adds
the button chrome around them, it never invents data.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace

from app import telegram_broadcast
from app.cities import city_label
from app.telegram_alerts import MAX_ACTIVE_ALERTS, create_or_get_alert
from app.telegram_job_search import (
    ROLE_FAMILY_LABELS,
    JobMasterEngine,
    JobMasterIntent,
    _role_label,
)
from app.telegram_waitlist import add_waitlist_entry

# Telegram callback_data has a hard 64-byte limit — every value below is
# well under it, and role buttons are addressed by index (not by keyword
# text) for exactly this reason.
BTN_PREFIX = '\x00'  # a real Telegram text message can never contain a NUL

FOCUS_EXPERIENCE = {'intern', 'fresher'}

EXPERIENCE_BUTTONS: list[tuple[str, str]] = [
    ('Intern', 'intern'),
    ('Fresher', 'fresher'),
    ('1–4 yrs', '1-4'),
    ('5–10 yrs', '5-10'),
    ('10+ yrs', '10plus'),
]
EXPERIENCE_LABELS = dict(EXPERIENCE_BUTTONS)

FAMILY_BUTTONS: list[tuple[str, str]] = [
    ('AI/ML', 'ai_ml'),
    ('Data', 'data'),
    ('Software', 'software'),
    ('Cybersecurity', 'cybersecurity'),
    ('Cloud/DevOps', 'cloud_devops'),
    ('Product', 'product'),
    ('Design', 'design'),
]

# (button label, role_keywords). role_family (from the family step) already
# gates the title via job_role_families.ROLE_FAMILY_REGEX; keywords here are
# only the extra word(s) that distinguish one button from its siblings, and
# deliberately never repeat a word already implied by the family label (see
# _role_label's dedupe fix — 2026-08-06 RCA).
ROLE_BUTTONS: dict[str, list[tuple[str, list[str]]]] = {
    'ai_ml': [
        ('ML Engineer', ['machine learning']),
        ('NLP Engineer', ['nlp']),
        ('Generative AI', ['generative']),
        ('Any AI/ML role', []),
    ],
    'data': [
        ('Data Analyst', ['analyst']),
        ('Data Scientist', ['scientist']),
        ('Data Engineer', ['engineer']),
        ('Business Intelligence', ['business intelligence']),
        ('Any Data role', []),
    ],
    'software': [
        ('Java Developer', ['java']),
        ('Python Developer', ['python']),
        ('Full Stack Developer', ['full stack', 'fullstack']),
        ('Frontend Developer', ['frontend']),
        ('Backend Developer', ['backend']),
        ('Any Software role', []),
    ],
    'cybersecurity': [
        ('SOC Analyst', ['soc']),
        ('Penetration Tester', ['penetration']),
        ('Security Engineer', ['security']),
        ('Any Cybersecurity role', []),
    ],
    'cloud_devops': [
        ('DevOps Engineer', ['devops']),
        ('Cloud Engineer', ['cloud']),
        ('Site Reliability (SRE)', ['reliability', 'sre']),
        ('Any Cloud/DevOps role', []),
    ],
    'product': [
        ('Product Manager', ['manager']),
        ('Product Owner', ['owner']),
        ('Product Analyst', ['analyst']),
        ('Any Product role', []),
    ],
    'design': [
        ('UI/UX Designer', ['ui/ux', 'ui/ ux', 'ux design']),
        ('Product Designer', ['product designer']),
        ('Graphic Designer', ['graphic']),
        ('Any Design role', []),
    ],
}

# Posting-freshness filter (Ashok, 2026-08-07: "another layer of filters
# such as 24hr, 2d, 1w after experience"). Values are calendar-day windows
# matching the same rolling-window vocabulary already used across the VIGIL
# dashboard (product-ux.mdc) and /api/jobs/insights: '0' = last 24 hours
# (freshest catches), '2'/'7' = last N calendar days, '' = no filter.
WINDOW_BUTTONS: list[tuple[str, str]] = [
    ('Last 24 hours', '0'),
    ('Last 2 days', '2'),
    ('This week', '7'),
    ('Any time', ''),
]

# Favourites first, matching the web dashboard's standing city-chip order
# (product-ux.mdc, 2026-08-02), then the rest, then Remote and Any city.
CITY_BUTTONS: list[tuple[str, str]] = [
    ('Bengaluru', 'bengaluru'),
    ('Chennai', 'chennai'),
    ('Kerala', 'kerala'),
    ('Hyderabad', 'hyderabad'),
    ('Pune', 'pune'),
    ('Mumbai', 'mumbai'),
    ('Delhi NCR', 'delhi'),
    ('Gurugram', 'gurugram'),
    ('Noida', 'noida'),
    ('Ahmedabad', 'ahmedabad'),
    ('Kolkata', 'kolkata'),
    ('Remote', 'remote'),
    ('Any city', ''),
]

WAITLIST_MESSAGE = (
    "Experienced-hire openings ({label}) are coming soon to JobMaster — "
    "we're focused on interns and freshers first. Share your email and "
    "we'll let you know the moment that opens up. (Or reply 'skip'.)"
)
WAITLIST_THANKS = "Got it — we'll email {email} the moment {label} openings go live. 🎯"
WAITLIST_SKIPPED = 'No worries — tap below whenever you want to look at intern/fresher openings instead.'

EMAIL_RE = re.compile(r"^[A-Za-z0-9_.+\-]+@[A-Za-z0-9\-]+\.[A-Za-z0-9\-.]+$")


@dataclass
class ButtonReply:
    """What a button-flow step wants sent back to the guest."""

    text: str
    keyboard: list[list[tuple[str, str]]] | None = field(default=None)


def _rows(buttons: list[tuple[str, str]], *, per_row: int = 2) -> list[list[tuple[str, str]]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _back_row(data: str) -> list[tuple[str, str]]:
    return [('◀ Back', data)]


class ButtonFlow:
    """Owns the Family -> Role -> Experience -> Window -> City -> Results
    wizard.

    Deliberately stateless between calls except for what is durably stored
    via TelegramSessionStore.save_onboarding/load_onboarding, under stage
    names prefixed 'btn_' so JobMasterEngine's legacy text onboarding (which
    only recognizes its own 'ask_*' stage names) safely and automatically
    treats a stale button-flow session as "unknown stage" and restarts
    itself — see _continue_onboarding's fallback branch. That is what makes
    plain typed text a safe, zero-extra-code backup path.
    """

    def __init__(self, engine: JobMasterEngine, sessions=None):
        self.engine = engine
        self.sessions = sessions if sessions is not None else engine.sessions

    # -- entry points ---------------------------------------------------

    def start(self, chat_id: str) -> ButtonReply:
        # Every guest who reaches the primary entry point is a broadcast
        # subscriber (Ashok, 2026-08-07) — /start, a bare greeting, and the
        # /new-triggered restart all funnel through here.
        telegram_broadcast.record_start(self.sessions, chat_id)
        profile = self.sessions.get_guest_profile(chat_id)
        if profile and profile.get('role_family') and profile.get('experience') in FOCUS_EXPERIENCE:
            label = profile.get('role_label') or _role_label(
                profile.get('role_family', ''), profile.get('role_keywords') or [],
            )
            city = profile.get('city') or ''
            city_txt = f' in {city_label(city)}' if city else ''
            self.sessions.save_onboarding(chat_id, {'stage': 'btn_welcome_back', **profile})
            text = (
                f'Welcome back! Last time you were looking for {label} '
                f'({profile.get("experience")}){city_txt}. Search that again?'
            )
            return ButtonReply(text, [[('Yes, same search', 'wb_yes')], [('New search', 'wb_no')]])
        return self._family_step()

    def _family_step(self) -> ButtonReply:
        return ButtonReply(
            'JobMaster here! What kind of role are you looking for?',
            _rows([(label, f'fam:{key}') for label, key in FAMILY_BUTTONS]),
        )

    # -- callback dispatch ------------------------------------------------

    def handle_callback(self, chat_id: str, data: str) -> ButtonReply:
        if data == 'wb_yes':
            return self._repeat_last_search(chat_id)
        if data == 'wb_no':
            self.sessions.clear_onboarding(chat_id)
            return self._family_step()
        if data == 'restart':
            self.sessions.clear(chat_id)
            self.sessions.clear_onboarding(chat_id)
            return self._family_step()
        if data == 'more':
            return self._more(chat_id)
        if data == 'alert:set':
            return self._set_alert(chat_id)
        if data.startswith('fam:'):
            return self._role_step(chat_id, data[len('fam:'):])
        if data == 'back:family' or data == 'reask:family':
            self.sessions.clear_onboarding(chat_id)
            return self._family_step()
        if data.startswith('role:'):
            _, family, idx_raw = data.split(':', 2)
            return self._experience_step(chat_id, family, idx_raw)
        if data == 'back:role' or data == 'reask:role':
            state = self._state(chat_id)
            family = state.get('role_family', '')
            return self._role_step(chat_id, family) if family else self._family_step()
        if data.startswith('exp:'):
            return self._on_experience(chat_id, data[len('exp:'):])
        if data == 'back:experience':
            return self._back_to_experience(chat_id)
        if data.startswith('window:'):
            return self._on_window(chat_id, data[len('window:'):])
        if data == 'back:window':
            return self._back_to_window(chat_id)
        if data.startswith('city:') or data == 'reask:city':
            idx_raw = data[len('city:'):] if data.startswith('city:') else ''
            return self._on_city(chat_id, idx_raw)
        # Unknown/expired callback (e.g. an old inline keyboard tapped after
        # a restart) — never leave the guest stuck with a dead button.
        return self._family_step()

    def handle_text(self, chat_id: str, text: str) -> ButtonReply | None:
        """Only consumes text while explicitly waiting for a waitlist email.
        Returns None for every other stage so the caller falls through to
        the existing free-text engine — the agreed 'backup plan'."""
        state = self._state(chat_id)
        if state.get('stage') != 'btn_waitlist_email':
            return None
        clean = text.strip()
        if clean.lower() in {'skip', 'no', 'no thanks', 'not now'}:
            self.sessions.clear_onboarding(chat_id)
            return ButtonReply(WAITLIST_SKIPPED, [[('Start a search', 'restart')]])
        if EMAIL_RE.match(clean):
            label = EXPERIENCE_LABELS.get(state.get('experience_choice', ''), state.get('experience_choice', ''))
            add_waitlist_entry(
                chat_id=chat_id,
                email=clean,
                experience=state.get('experience_choice', ''),
                role_family=state.get('role_family', ''),
            )
            self.sessions.clear_onboarding(chat_id)
            return ButtonReply(
                WAITLIST_THANKS.format(email=clean, label=label),
                [[('Search Intern/Fresher roles', 'restart')]],
            )
        return ButtonReply(
            "That doesn't look like a valid email — try again, or reply 'skip'."
        )

    # -- steps ------------------------------------------------------------

    def _role_step(self, chat_id: str, family: str) -> ButtonReply:
        options = ROLE_BUTTONS.get(family, [])
        if not options:
            return self._family_step()
        family_label = ROLE_FAMILY_LABELS.get(family, family.replace('_', ' ').title())
        self.sessions.save_onboarding(chat_id, {'stage': 'btn_role', 'role_family': family})
        buttons = [(label, f'role:{family}:{idx}') for idx, (label, _kw) in enumerate(options)]
        return ButtonReply(
            f'{family_label} — which role?',
            _rows(buttons) + [_back_row('back:family')],
        )

    def _experience_step(self, chat_id: str, family: str, idx_raw: str) -> ButtonReply:
        options = ROLE_BUTTONS.get(family, [])
        try:
            idx = int(idx_raw)
            label, keywords = options[idx]
        except (ValueError, IndexError):
            return self._role_step(chat_id, family)
        self.sessions.save_onboarding(chat_id, {
            'stage': 'btn_experience',
            'role_family': family,
            'role_keywords': keywords,
            'role_label_choice': label,
        })
        return self._render_experience_step(label)

    def _render_experience_step(self, role_label: str) -> ButtonReply:
        buttons = [(label, f'exp:{code}') for label, code in EXPERIENCE_BUTTONS]
        return ButtonReply(
            f'Got it — {role_label}. What is your experience level?',
            _rows(buttons, per_row=3) + [_back_row('back:role')],
        )

    def _on_experience(self, chat_id: str, code: str) -> ButtonReply:
        state = self._state(chat_id)
        family = state.get('role_family', '')
        if not family:
            return self._family_step()
        label = EXPERIENCE_LABELS.get(code, code)
        if code not in FOCUS_EXPERIENCE:
            self.sessions.save_onboarding(chat_id, {
                **state,
                'stage': 'btn_waitlist_email',
                'experience_choice': code,
            })
            return ButtonReply(WAITLIST_MESSAGE.format(label=label))
        self.sessions.save_onboarding(chat_id, {
            **state,
            'stage': 'btn_window',
            'experience_choice': code,
        })
        return self._render_window_step(label)

    def _render_window_step(self, experience_label: str) -> ButtonReply:
        buttons = [(label, f'window:{code}') for label, code in WINDOW_BUTTONS]
        return ButtonReply(
            f'Got it — {experience_label}. How fresh should the postings be?',
            _rows(buttons) + [_back_row('back:experience')],
        )

    def _back_to_experience(self, chat_id: str) -> ButtonReply:
        state = self._state(chat_id)
        family = state.get('role_family', '')
        if not family:
            return self._family_step()
        return self._render_experience_step(state.get('role_label_choice', ''))

    def _on_window(self, chat_id: str, code: str) -> ButtonReply:
        state = self._state(chat_id)
        family = state.get('role_family', '')
        if not family:
            return self._family_step()
        self.sessions.save_onboarding(chat_id, {
            **state,
            'stage': 'btn_city',
            'window_choice': code,
        })
        return self._render_city_step()

    def _render_city_step(self) -> ButtonReply:
        buttons = [(label, f'city:{idx}') for idx, (label, _key) in enumerate(CITY_BUTTONS)]
        return ButtonReply(
            'Any city preference?',
            _rows(buttons) + [_back_row('back:window')],
        )

    def _back_to_window(self, chat_id: str) -> ButtonReply:
        state = self._state(chat_id)
        family = state.get('role_family', '')
        if not family:
            return self._family_step()
        code = state.get('experience_choice', '')
        return self._render_window_step(EXPERIENCE_LABELS.get(code, code))

    def _on_city(self, chat_id: str, idx_raw: str) -> ButtonReply:
        state = self._state(chat_id)
        family = state.get('role_family', '')
        if not family:
            return self._family_step()
        try:
            idx = int(idx_raw)
            city_key = CITY_BUTTONS[idx][1]
        except (ValueError, IndexError):
            city_key = ''
        window_choice = state.get('window_choice', '')
        posted_within_days = int(window_choice) if window_choice not in ('', None) else None
        intent = JobMasterIntent(
            kind='job_search',
            role_family=family,
            role_keywords=state.get('role_keywords') or [],
            cities=[city_key] if city_key else [],
            experience='fresher',  # both Intern and Fresher search the same
                                    # live "fresher" track (LinkedIn
                                    # Internship + Entry level) — see
                                    # documents/roadmap.md.
            posted_within_days=posted_within_days,
        )
        display_experience = state.get('experience_choice') or 'fresher'
        self.sessions.clear_onboarding(chat_id)
        return self._run_search(chat_id, intent, display_experience=display_experience)

    def _repeat_last_search(self, chat_id: str) -> ButtonReply:
        state = self._state(chat_id)
        intent = JobMasterIntent(
            kind='job_search',
            role_family=state.get('role_family', ''),
            role_keywords=state.get('role_keywords') or [],
            cities=[state['city']] if state.get('city') else [],
            experience='fresher',
            # guest_profiles doesn't remember a freshness preference (only
            # role/experience/city) — "Welcome back" repeats with no window
            # filter (any time) rather than guessing a stale one.
            posted_within_days=None,
        )
        display_experience = state.get('experience') or 'fresher'
        self.sessions.clear_onboarding(chat_id)
        return self._run_search(chat_id, intent, display_experience=display_experience)

    def _run_search(
        self, chat_id: str, intent: JobMasterIntent, *, display_experience: str = 'fresher',
    ) -> ButtonReply:
        chosen_intent = intent  # what the guest actually picked — used for the
                                 # remembered guest profile, even if broadened below.
        search_intent = intent
        reply_text, seen_ids = self.engine._job_reply(intent, seen_ids=[])
        broadened_from = ''
        if intent.role_keywords and 'No verified jobs' in reply_text:
            # A specific role button (e.g. "NLP Engineer") can easily have
            # zero live postings at any given moment even though its family
            # has plenty — a narrow button tap should never dead-end a guest
            # when a wider, still-honest, same-family result exists. This
            # only ever widens *within* the chosen family (role_keywords=[]
            # is exactly what "Any <Family> role" already searches) — it
            # never substitutes a different family, so JM056's "no
            # substitution across categories" contract still holds.
            broader_intent = replace(intent, role_keywords=[])
            broader_reply, broader_seen = self.engine._job_reply(broader_intent, seen_ids=[])
            if 'No verified jobs' not in broader_reply:
                broadened_from = _role_label(intent.role_family, intent.role_keywords)
                search_intent = broader_intent
                reply_text, seen_ids = broader_reply, broader_seen
        window_relaxed = False
        if search_intent.posted_within_days is not None and 'No verified jobs' in reply_text:
            # A tight freshness filter (2026-08-07, e.g. "Last 24 hours") is
            # the single most likely reason for an otherwise-real search to
            # dead-end — never let it silently zero out a guest's results
            # when older-but-still-live postings exist. Same "never dead-end
            # a guest" philosophy as the role-widening step above.
            wider_intent = replace(search_intent, posted_within_days=None)
            wider_reply, wider_seen = self.engine._job_reply(wider_intent, seen_ids=[])
            if 'No verified jobs' not in wider_reply:
                window_relaxed = True
                search_intent = wider_intent
                reply_text, seen_ids = wider_reply, wider_seen
        self.sessions.apply_result(
            chat_id,
            reply_text,
            intent=asdict(search_intent),
            page=0,
            seen_ids=seen_ids,
        )
        self.engine._maybe_save_guest_profile(chat_id, chosen_intent)
        # Overwrite with the guest's own word (Intern vs Fresher) for a
        # truer "Welcome back" later — the query itself always uses the
        # shared 'fresher' track (see comment above), but the guest's
        # self-identified choice (not the broadened search) is worth
        # remembering accurately.
        self.sessions.save_guest_profile(
            chat_id,
            role_label=_role_label(chosen_intent.role_family, chosen_intent.role_keywords),
            role_family=chosen_intent.role_family,
            role_keywords=chosen_intent.role_keywords,
            experience=display_experience,
            city=chosen_intent.cities[0] if chosen_intent.cities else '',
        )
        prefix_lines: list[str] = []
        if broadened_from:
            family_label = ROLE_FAMILY_LABELS.get(
                search_intent.role_family, search_intent.role_family.replace('_', ' ').title(),
            )
            prefix_lines.append(
                f'No {broadened_from} openings right now — here are other '
                f'{family_label} roles instead.'
            )
        if window_relaxed:
            prefix_lines.append('No openings in that time window — showing all recent matches instead.')
        if prefix_lines:
            reply_text = '\n'.join(prefix_lines) + f'\n\n{reply_text}'
        actions: list[tuple[str, str]] = []
        if 'No verified jobs' in reply_text or 'No more verified jobs' in reply_text:
            actions = [('Try another role', 'reask:role'), ('Try another family', 'reask:family')]
        else:
            if 'Reply more' in reply_text:
                actions.append(('More jobs ▸', 'more'))
            actions.append(('🔔 Set alert', 'alert:set'))
            actions.append(('🔄 New search', 'restart'))
        return ButtonReply(reply_text, _rows(actions, per_row=1) if actions else None)

    def _more(self, chat_id: str) -> ButtonReply:
        reply_text = self.engine.handle('more', chat_id)
        actions: list[tuple[str, str]] = []
        if 'Reply more' in reply_text:
            actions.append(('More jobs ▸', 'more'))
        actions.append(('🔔 Set alert', 'alert:set'))
        actions.append(('🔄 New search', 'restart'))
        return ButtonReply(reply_text, _rows(actions, per_row=1))

    def _set_alert(self, chat_id: str) -> ButtonReply:
        """"Set alert every day" (Ashok, 2026-08-07) — reuses whatever
        search_intent produced the results the guest is currently looking
        at (the same thing 'more' paginates), so the alert always matches
        what they actually just saw, including any narrow->family
        broadening _run_search already applied."""
        saved = self.sessions.load_search(chat_id)
        if not saved:
            return ButtonReply('Search for a role first, then tap "Set alert" on the results.')
        intent_dict, _page, seen_ids = saved
        intent = JobMasterIntent(**intent_dict)
        role_label = _role_label(intent.role_family, intent.role_keywords)
        city = intent.cities[0] if intent.cities else ''
        _alert, status = create_or_get_alert(
            self.sessions,
            chat_id,
            role_family=intent.role_family,
            role_keywords=intent.role_keywords,
            role_label=role_label,
            city=city,
            experience='fresher',
            seen_ids=seen_ids,
        )
        city_txt = f' in {city_label(city)}' if city else ''
        if status == 'limit':
            return ButtonReply(
                f"You're already tracking {MAX_ACTIVE_ALERTS} alerts — the max for now. "
                'Send /myalerts to see or stop one.'
            )
        if status == 'exists':
            return ButtonReply(
                f'🔔 Alert for {role_label}{city_txt} is already ON — you\'ll hear '
                'about new matches here about once a day.'
            )
        return ButtonReply(
            f'🔔 Alert set for {role_label}{city_txt}. '
            "I'll message you here whenever new matching jobs appear (about once a day). "
            'Send /myalerts anytime to manage or stop it.'
        )

    def _state(self, chat_id: str) -> dict:
        return self.sessions.load_onboarding(chat_id) or {}
