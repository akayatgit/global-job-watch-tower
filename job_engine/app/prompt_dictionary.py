"""Prompt length + style knobs for DIRECTOR → LENS.

Ashok 2026-08-04: do NOT hardcode fixed scene prompts in source.
DIRECTOR invents each prompt. We only enforce minimum length and keep
tunable constants for later (raise/lower based on response quality).
"""

from __future__ import annotations

# Tunable — raise/lower later based on response quality
MIN_PROMPT_CHARS = 800

# Soft style keywords DIRECTOR may weave in (not a fixed scene paste)
STYLE_INSPIRATION_KEYWORDS = (
    'minimalist high-contrast graphic design',
    'premium marketing aesthetic',
    'hyper-clean vector graphic',
    'bold dual-weight sans-serif typography layered on graphic',
    'perfectly symmetrical matte black silhouette concept',
    'solid bright background with faint subtle grid',
    'electric blue OR vivid orange OR neon green OR hot magenta OR sun yellow',
    'punchline poster / skit beat / Pinterest 2026 editorial',
    'Tamil Nadu regional energy without stereotype spam',
    'studio lighting, clean composition, no photo-realistic office atrium',
    'no white UI cards, no frosted glass panels, no holographic India map cliché',
)

# Tunable brief for DIRECTOR + fallbacks — NOT a paste-in Replicate scene.
# Expand/rewrite later when Ashok judges image quality.
GRAPHIC_STYLE_BRIEF = (
    'Create an original 2D graphic design advertising poster in the spirit of '
    'minimalist high-contrast premium marketing: choose ONE vivid solid background '
    '(electric blue, vivid orange, neon green, hot magenta, or sun yellow — never '
    'reuse the same color as the last frame). Add only a faint subtle grid. Place a '
    'perfectly symmetrical striking silhouette or bold concept mark in solid matte '
    'black at dead center. Layer bold modern dual-weight sans-serif typography '
    'directly over that black graphic — the punchline is the hero text, secondary '
    'fact line smaller underneath. Hyper-clean vector look, studio lighting, '
    'premium ad aesthetic, simple clean composition, lots of intentional negative '
    'space. The image must answer as a punchline skit beat for TECH JOB MARKET '
    'MOVEMENT by JobMaster.agency · Vigil · AI · Quanta HR. Forbidden: photoreal '
    'glass atriums, holographic India maps, frosted white UI cards, caption boxes, '
    'rounded glass panels, soft essay serif blocks, recycled office stock looks. '
    'Invent a fresh black silhouette metaphor each time (ladder, spark, door, wave, '
    'compass, fist of hope, rising bars as abstract shapes — not charts). Include '
    'exact punchline words to render as designed type inside the artwork.'
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
    """Long graphic prompt for /new and rescue — still invented structure, not atrium cliché."""
    colors = {
        'reset': 'vivid orange',
        'rescue': 'electric blue',
        'pulse': 'neon green',
    }
    silhouettes = {
        'reset': 'a blank chalkboard wiped clean transforming into a rising staircase silhouette',
        'rescue': 'a listening ear merging with a lighthouse beam as one matte black mark',
        'pulse': 'abstract rising bars becoming a forward-leaning runner silhouette',
    }
    bg = colors.get(mood, 'hot magenta')
    sil = silhouettes.get(mood, silhouettes['rescue'])
    punch = (punchline or 'JobMaster is listening').strip()[:120]
    fact = (fact_line or 'Live tower facts').strip()[:140]
    prompt = (
        f'{GRAPHIC_STYLE_BRIEF} '
        f'This beat mood is "{mood}". Background: solid {bg} with faint subtle grid. '
        f'Central matte black graphic: {sil}. '
        f'Render primary typography exactly as: "{punch}". '
        f'Render secondary typography exactly as: "{fact}". '
        f'Brand whisper small at edge: JobMaster.agency · Vigil · Quanta HR. '
        f'Composition is dead-center symmetrical, hyper-clean vector, premium marketing, '
        f'studio lighting, no photo realism, no white cards, no glass atrium, no India hologram. '
        f'The whole poster must feel like a punchline reply from a powerful DIRECTOR who knows '
        f'the TECH job market movement for Tamil Nadu seekers — hope and truth, not fear. '
        f'Add one wow detail: a single geometric accent (thin circle or slash) in the same '
        f'family as the background color but slightly lighter, never cluttering the type. '
        f'Aspect square social poster. Ultra sharp edges. No mock UI. No watermarks. '
        f'Leave generous negative space around the black mark so the typography reads instantly '
        f'on Telegram at phone size. Make it look like a campaign ad, not a dashboard screenshot.'
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
    """800+ char graphic prompt with typography baked in — no Pillow overlay."""
    palette = {
        'hook': 'electric blue',
        'pulse': 'neon green',
        'rising': 'vivid orange',
        'hirer': 'hot magenta',
        'fresher': 'sun yellow',
        'cta': 'electric blue',
        'topic-hook': 'vivid orange',
        'date': 'neon green',
        'companies': 'electric blue',
        'more': 'hot magenta',
    }
    marks = {
        'hook': 'question-mark dissolving into an open door silhouette',
        'pulse': 'heartbeat line becoming a city skyline silhouette',
        'rising': 'arrow formed from abstract steps climbing upward',
        'hirer': 'handshake reduced to two interlocking geometric shapes',
        'fresher': 'seed sprout inside a bold geometric shield',
        'cta': 'compass needle pointing northeast as a single black mark',
        'topic-hook': 'magnifying glass over a rising path silhouette',
        'date': 'calendar page folded into a sharp geometric wing',
        'companies': 'cluster of abstract building stubs as one crest',
        'more': 'stacked list marks becoming a ladder silhouette',
    }
    bg = palette.get(slide_key, 'vivid orange')
    sil = marks.get(slide_key, 'bold abstract spark silhouette')
    h = ' · '.join(x.strip() for x in headline.replace('\n', ' · ').split('·') if x.strip())[:160]
    s = sub.replace('\n', ' · ').strip()[:140]
    st = stat.replace('\n', ' · ').strip()[:160]
    role_bit = f' Role focus: {role_hint}.' if role_hint else ''
    prompt = (
        f'{GRAPHIC_STYLE_BRIEF} '
        f'Carousel slide key "{slide_key}". Solid {bg} background, faint grid. '
        f'Central matte black concept: {sil}.{role_bit} '
        f'Render hero typography exactly: "{h}". '
        f'Render supporting line: "{s}". '
        f'Render fact block as designed bold type (not a UI card): "{st}". '
        f'Small edge brand: TECH JOB MARKET MOVEMENT · JobMaster.agency. '
        f'Vertical 3:4 social poster, dead-center composition, hyper-clean vector, '
        f'premium marketing, punchline-first, Tamil Nadu creative energy without stereotypes. '
        f'No white frosted panels, no glass atrium, no holographic maps, no photo-real graduates. '
        f'Typography must be integral to the graphic — letterforms can intersect the black mark. '
        f'Studio lighting, sharp edges, campaign-ready, readable on a phone in Telegram albums. '
        f'Vary silhouette and color from other slides; this slide must feel unique in the set. '
        f'Negative space generous. One geometric accent only. Ultra premium ad finish.'
    )
    return assert_prompt_length(prompt)
