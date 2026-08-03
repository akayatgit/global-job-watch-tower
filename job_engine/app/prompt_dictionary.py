"""Prompt length + style knobs for DIRECTOR → LENS.

Ashok 2026-08-04:
- Style brief = DIRECTOR brain only. NEVER paste into Replicate prompts.
- Replicate prompt = pure visual description + tiny on-image text + live facts.
"""

from __future__ import annotations

# Tunable — raise/lower later based on response quality
MIN_PROMPT_CHARS = 800

# Soft keywords for DIRECTOR thinking (not for Replicate paste)
STYLE_INSPIRATION_KEYWORDS = (
    'real-time Jarvis briefing glance',
    'casual visual conversation about live data',
    'minimal punchy words — 2 to 6 words hero max',
    'data-as-visual: numbers roles companies heat as graphic beats',
    'clean high-contrast 2D illustration, not a marketing poster',
    'not PowerPoint, not carousel ad, not campaign CTA',
    'vary palette and metaphor every turn',
    'tower pulse / signal / heat / hiring motion as metaphor',
    'fun witty buddy energy with Ashok',
    'no frosted UI cards, no atrium stock, no India hologram cliché',
)

# DIRECTOR instructions only — must NEVER appear in Replicate prompts
GRAPHIC_STYLE_BRIEF = (
    'Private ops Jarvis for Ashok: casual fun visual discussion of live tower data. '
    'Tiny on-image text (2–6 words + one fact crumb). Data is the star. '
    'Not student posters, not PPT, not campaign ads. Invent a fresh illustration each turn. '
    'Translate this brief into a concrete visual scene — never copy this paragraph into the image prompt.'
)

# Phrases that mean DIRECTOR (or rescue) leaked policy text into the image prompt
_LEAK_MARKERS = (
    'real-time jarvis visual reply',
    'not a student poster',
    'not a powerpoint',
    'ashok chatting',
    'fallback mood',
    'graphic_style_brief',
    'never invent fake',
    'private ops chat visual',
    'forbidden: ppt',
)


def assert_prompt_length(prompt: str) -> str:
    p = (prompt or '').strip()
    if len(p) < MIN_PROMPT_CHARS:
        raise ValueError(
            f'Prompt too short ({len(p)} chars). Need >= {MIN_PROMPT_CHARS}. '
            'Expand with concrete visual detail: subject, composition, colors, lighting, '
            'typography placement, mood — not policy essays.'
        )
    return p


def assert_visual_prompt(prompt: str) -> str:
    """Length + no style-brief / policy leakage into Replicate."""
    p = assert_prompt_length(prompt)
    low = p.lower()
    for m in _LEAK_MARKERS:
        if m in low:
            raise ValueError(
                f'Prompt leaked style-policy text ({m!r}). Rewrite as a pure visual '
                'description for the image model: scene, colors, shapes, lighting, '
                'exact short on-image words, live fact crumb.'
            )
    return p


def fallback_graphic_prompt(*, punchline: str, fact_line: str, mood: str = 'reset') -> str:
    """Pure visual rescue/reset prompt — no DIRECTOR policy brief inside."""
    scenes = {
        'reset': (
            'deep charcoal square, single electric cyan radar ring sweeping once, '
            'soft vignette, one thin geometric slash accent'
        ),
        'rescue': (
            'midnight navy square, warm amber pulse circle behind a simple ear-and-tower '
            'icon in matte black, quiet depth, one thin amber arc accent'
        ),
        'heat': (
            'dark graphite square, vertical heat-gauge silhouette in matte black with a '
            'warm orange fill rising partway, subtle grid, one ember accent spark'
        ),
        'pulse': (
            'ink black square, neon green signal spike as a single clean mark, '
            'asymmetric layout, one cyan tick accent'
        ),
    }
    scene = scenes.get(mood, scenes['rescue'])
    punch = (punchline or 'Tower online').strip()[:40]
    fact = (fact_line or 'live pulse').strip()[:70]
    prompt = (
        f'Hyper-clean 2D vector illustration for a phone chat glance. {scene}. '
        f'High contrast, playful ops-buddy energy, generous negative space, sharp edges, '
        f'no photorealism, no glass atrium, no frosted white cards, no India hologram, '
        f'no PowerPoint title bar, no campaign CTA button. '
        f'Draw bold dual-weight sans-serif typography into the artwork itself: '
        f'hero line exactly "{punch}" near the central mark; '
        f'one smaller fact crumb exactly "{fact}" under it. '
        f'Keep all on-image words tiny and punchy — nothing else written on the image. '
        f'Studio-clean lighting with soft falloff, slight depth so the central mark reads '
        f'first, then the number. Composition readable at Telegram thumbnail size. '
        f'Asymmetric but balanced. Premium illustration finish, not a marketing poster. '
        f'Describe the metaphor clearly: the graphic should make the fact feel obvious at a '
        f'glance. Square 1:1 frame. No watermarks, no UI chrome, no long paragraphs, '
        f'no slogan walls, no brand parade. One wow geometric accent only. '
        f'Color mood stays consistent with the scene description above; edges crisp; '
        f'background flat or faintly graded; central icon solid and iconic. '
        f'The image should feel like a smart friend flashing a status glance — witty, short, '
        f'data-first — while remaining a concrete visual for an image generator to paint.'
    )
    return assert_visual_prompt(prompt)


def graphic_carousel_prompt(
    *,
    slide_key: str,
    headline: str,
    sub: str,
    stat: str,
    role_hint: str = '',
) -> str:
    h = ' · '.join(x.strip() for x in headline.replace('\n', ' · ').split('·') if x.strip())[:100]
    s = sub.replace('\n', ' · ').strip()[:80]
    st = stat.replace('\n', ' · ').strip()[:100]
    role_bit = f' Role focus cue in the metaphor only: {role_hint}.' if role_hint else ''
    prompt = (
        f'Hyper-clean 2D vector illustration, vertical 3:4 social frame, slide feel "{slide_key}".'
        f'{role_bit} Invent a unique data metaphor (signal, gauge, path, cluster marks) — '
        f'not a PowerPoint slide, not a campaign poster. High contrast, lively asymmetric '
        f'composition, generous negative space, sharp edges, no frosted cards, no atrium stock, '
        f'no India hologram. Draw typography into the art: hero "{h}"; crumb "{s}"; '
        f'fact "{st}". Tiny punchy words only. Studio-clean lighting, phone-readable, '
        f'one geometric accent, premium illustration finish. Expand with concrete color, '
        f'lighting, depth, and placement detail so the prompt stays richly visual and long '
        f'enough for a strong Grok Imagine render without any policy-essay language.'
    )
    return assert_visual_prompt(prompt)
