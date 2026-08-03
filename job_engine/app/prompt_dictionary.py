"""Prompt length + style knobs for DIRECTOR → LENS.

Ashok 2026-08-04: no fixed scene paste in source. DIRECTOR invents prompts.
Telegram = Ashok talking to the Tower (Jarvis), NOT student posters/PPT.
"""

from __future__ import annotations

# Tunable — raise/lower later based on response quality
MIN_PROMPT_CHARS = 800

# Soft keywords DIRECTOR may weave (not a fixed scene)
STYLE_INSPIRATION_KEYWORDS = (
    'real-time Jarvis briefing glance',
    'casual visual conversation about live data',
    'minimal punchy words only — 2 to 6 words hero max',
    'data-as-visual: numbers roles companies as graphic beats',
    'clean high-contrast 2D illustration, not a marketing poster',
    'not PowerPoint, not carousel ad, not campaign CTA',
    'bright or dark stage — invent; vary every turn',
    'tower pulse / signal / heat / hiring motion as metaphor',
    'fun witty buddy energy with Ashok',
    'no frosted UI cards, no atrium stock, no India hologram cliché',
)

# Tunable brief — rewrite later when Ashok judges frames
GRAPHIC_STYLE_BRIEF = (
    'You are rendering a REAL-TIME JARVIS visual reply for Ashok chatting with '
    'Watch Tower — a casual fun visual discussion of live job-market data, NOT a '
    'student poster, NOT a PowerPoint slide, NOT a social-media campaign ad. '
    'Invent a fresh illustrative frame each turn that feels like a smart friend '
    'showing him what is happening in the tower right now. Minimal on-image text: '
    'one tiny punchy line (roughly 2–6 words) plus at most one short fact crumb '
    '(a number, role, or company) — never essays, never hope slogans for students, '
    'never “Do I still have hope?” energy. Make the DATA the star: openings today, '
    'rising role, top hirer, heat, next search — shown as graphic conversation, '
    'diagram-ish motion, icon metaphor, signal pulse, abstract bars-as-shapes, '
    'city/company marks — whatever fits the beat. Composition can be asymmetric and '
    'lively; high-contrast; hyper-clean 2D/vector illustration; readable on a phone. '
    'Vary palette and metaphor every reply. Forbidden: PPT title slides, poster CTAs, '
    'frosted white caption cards, glass atrium stock, holographic India maps, '
    'recycled graduate-at-window photos, long serif paragraphs. Typography is drawn '
    'into the art (no later overlay). Tone: witty, short, powerful, ops-buddy Jarvis.'
)


def assert_prompt_length(prompt: str) -> str:
    p = (prompt or '').strip()
    if len(p) < MIN_PROMPT_CHARS:
        raise ValueError(
            f'Prompt too short ({len(p)} chars). Need >= {MIN_PROMPT_CHARS}. '
            'Expand with subject, action, composition, color, typography, mood, wow element.'
        )
    return p


def fallback_graphic_prompt(*, punchline: str, fact_line: str, mood: str = 'reset') -> str:
    """Jarvis fallback for /new and rescue — casual tower pulse, not a poster."""
    moods = {
        'reset': (
            'deep charcoal stage with one electric cyan signal ring',
            'a small radar sweep mark as the only hero graphic',
        ),
        'rescue': (
            'midnight navy with a warm amber pulse',
            'an ear-to-tower icon as a single clean mark',
        ),
        'pulse': (
            'ink black with neon green tick marks',
            'a heartbeat signal becoming a simple rising spike',
        ),
    }
    bg, sil = moods.get(mood, moods['rescue'])
    punch = (punchline or 'Tower online').strip()[:40]
    fact = (fact_line or 'live pulse').strip()[:60]
    prompt = (
        f'{GRAPHIC_STYLE_BRIEF} '
        f'Fallback mood "{mood}". Scene: {bg}. Central mark: {sil}. '
        f'Render tiny hero text exactly: "{punch}". '
        f'Render one fact crumb exactly: "{fact}". '
        f'No brand slogan wall. No student CTA. No PPT layout. '
        f'Feel like Jarvis whispering a status glance to Ashok on Telegram. '
        f'Square frame, sharp, playful, data-first, generous empty space, '
        f'one wow geometric accent only. Ultra clean illustration, not a poster campaign. '
        f'Describe lighting, depth, negative space, and why the metaphor matches the fact. '
        f'Keep every word on the image short and punchy. Never invent fake job numbers — '
        f'only render the fact crumb given. This is a private ops chat visual, not public ads.'
    )
    return assert_prompt_length(prompt)


def graphic_carousel_prompt(
    *,
    slide_key: str,
    headline: str,
    sub: str,
    stat: str,
    role_hint: str = '',
) -> str:
    """Carousel is the separate student Movement product — still graphic, not PPT chrome."""
    # Keep carousel usable when Ashok says the magic word; chat path stays Jarvis.
    h = ' · '.join(x.strip() for x in headline.replace('\n', ' · ').split('·') if x.strip())[:100]
    s = sub.replace('\n', ' · ').strip()[:80]
    st = stat.replace('\n', ' · ').strip()[:100]
    role_bit = f' Role focus: {role_hint}.' if role_hint else ''
    prompt = (
        f'{GRAPHIC_STYLE_BRIEF} '
        f'This is a CAROUSEL album frame (key={slide_key}) for when Ashok asks Carousel — '
        f'still visual-data conversation energy, not a corporate PPT deck.{role_bit} '
        f'Render short hero: "{h}". Support crumb: "{s}". Fact: "{st}". '
        f'Vertical 3:4. Invent a unique data metaphor for this slide. '
        f'No frosted cards, no atrium, no India hologram, no long essays. '
        f'Keep on-image text tiny and punchy. Make the number/role/company impossible to miss. '
        f'Describe composition, color, lighting, negative space, and one wow detail so the '
        f'prompt stays richly specific and longer than eight hundred characters with clear '
        f'instructions for Grok Imagine to draw typography into the illustration itself.'
    )
    return assert_prompt_length(prompt)
