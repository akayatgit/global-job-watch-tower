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


# ---------------------------------------------------------------------------
# Carousel art direction (Ashok 2026-08-04: "the current carousel is shitty,
# it is sticking to one prompt, and creates the same") — one theme per RUN
# (coherent album), rotating across runs so no two carousels look alike, and
# a distinct layout per SLIDE ROLE so the set reads like a designed series,
# not six renders of the same template. Facts stay verbatim tower numbers.
# ---------------------------------------------------------------------------

CAROUSEL_THEMES: tuple[dict, ...] = (
    {
        'name': 'midnight editorial',
        'canvas': 'near-black graphite background with a barely visible fine dot grid',
        'ink': 'warm off-white typography',
        'accent': 'one electric cyan accent only',
        'type': 'huge modern editorial serif display for hero numbers and words, small clean sans-serif for crumbs',
        'finish': 'matte print finish, hairline rules separating zones, museum-poster restraint',
    },
    {
        'name': 'swiss paper minimal',
        'canvas': 'warm paper off-white background, flat, no texture noise',
        'ink': 'pure ink-black typography',
        'accent': 'a single vermilion red-orange accent bar or dot',
        'type': 'massive tight grotesque sans-serif, strict swiss grid alignment, dramatic size contrast between hero and crumb',
        'finish': 'clean international-typographic-style poster, huge negative space, zero decoration beyond the grid',
    },
    {
        'name': 'terminal pulse',
        'canvas': 'very dark green-black console background with a faint scanline sheen',
        'ink': 'phosphor green data marks and typography',
        'accent': 'one amber warning-light accent',
        'type': 'bold monospaced terminal typography, numbers oversized like a trading screen',
        'finish': 'crisp glowing edges on type only, everything else flat and dark, ops-room energy',
    },
    {
        'name': 'dusk gradient signal',
        'canvas': 'smooth deep-violet to ember-orange vertical gradient background',
        'ink': 'white typography with soft glow only on the hero number',
        'accent': 'thin glowing signal line arcing across the composition',
        'type': 'rounded geometric sans-serif, hero number enormous and centered',
        'finish': 'premium fintech-app hero-screen feel, soft depth, no cards or panels',
    },
    {
        'name': 'brutalist poster',
        'canvas': 'single solid electric cobalt-blue background, completely flat',
        'ink': 'gigantic white typography bleeding slightly off the frame edges',
        'accent': 'one black underline slab',
        'type': 'ultra-heavy condensed sans-serif, hero word or number fills half the frame',
        'finish': 'loud modern brutalist gallery poster, confident, zero gradients, zero icons',
    },
    {
        'name': 'ink and gold',
        'canvas': 'deep charcoal background with a whisper of dark marble texture',
        'ink': 'champagne-gold typography and thin gold rules',
        'accent': 'one small warm-white highlight on the key number',
        'type': 'elegant high-contrast serif for heroes, letter-spaced small caps for crumbs',
        'finish': 'luxury annual-report cover feel, precise, quiet, expensive',
    },
)

# Slide-role layouts — concrete compositions, not "invent a metaphor"
_CAROUSEL_LAYOUTS: dict[str, str] = {
    'hook': (
        'Cover slide. The hero question fills the top two-thirds in enormous type, '
        'stacked in two or three ragged lines with strong hierarchy. The series name '
        'sits small at the very bottom edge like a publication footer. No imagery '
        'besides typography and the single accent element.'
    ),
    'big-number': (
        'Stat hero slide. One enormous numeral dominates dead center at roughly half '
        'the frame height, with the label in small type directly above it and the '
        'secondary count in small type below. The accent element points at or '
        'underlines the number.'
    ),
    'ranked-list': (
        'Ranked list slide. A clean left-aligned column of five short rows, each row '
        'exactly one name and one number, separated by hairline rules, biggest value '
        'on top with its row rendered slightly larger and in the accent treatment. '
        'Title in small caps at the top. Numbers right-aligned in a tidy column.'
    ),
    'rising': (
        'Momentum slide. One steep clean ascending line or arrow travels from the '
        'bottom-left toward the top-right of the frame in the accent treatment; '
        'the role name sits at the line\'s peak in large type with the +delta '
        'number attached to it like a badge. Small label at the bottom-left origin.'
    ),
    'stat-chips': (
        'Snapshot slide. Two or three short stat pairs arranged as an airy vertical '
        'stack — each pair is a small label over a large number — separated by '
        'generous whitespace, all left-aligned on the grid. No boxes around them.'
    ),
    'cta': (
        'Closing slide. The sign-off phrase large in the upper third, the brand line '
        'small and centered near the bottom, and the single accent element between '
        'them acting as a full stop. Calmest slide of the set.'
    ),
}

# Map every known slide key to a layout role
_SLIDE_LAYOUT_BY_KEY: dict[str, str] = {
    'hook': 'hook',
    'topic-hook': 'hook',
    'pulse': 'big-number',
    'date': 'stat-chips',
    'rising': 'rising',
    'hirer': 'big-number',
    'companies': 'ranked-list',
    'more': 'ranked-list',
    'fresher': 'stat-chips',
    'cta': 'cta',
}


def pick_carousel_theme(run_seed: int) -> dict:
    """Stable within one run, rotates across runs — no two albums alike."""
    return CAROUSEL_THEMES[run_seed % len(CAROUSEL_THEMES)]


def graphic_carousel_prompt(
    *,
    slide_key: str,
    headline: str,
    sub: str,
    stat: str,
    role_hint: str = '',
    theme: dict | None = None,
    run_seed: int = 0,
) -> str:
    theme = theme or pick_carousel_theme(run_seed)
    layout = _CAROUSEL_LAYOUTS.get(_SLIDE_LAYOUT_BY_KEY.get(slide_key, 'big-number'))

    h = ' · '.join(x.strip() for x in headline.replace('\n', ' · ').split('·') if x.strip())[:100]
    s = sub.replace('\n', ' · ').strip()[:80]
    st = stat.replace('\n', ' · ').strip()[:120]
    role_bit = f' Subtle nod to the role "{role_hint}" in the accent element only.' if role_hint else ''

    prompt = (
        f'Modern minimal social-media graphic, vertical 3:4 frame, "{theme["name"]}" art direction. '
        f'{theme["canvas"].capitalize()}. {theme["ink"].capitalize()}. {theme["accent"].capitalize()}. '
        f'Typography: {theme["type"]}. Finish: {theme["finish"]}. '
        f'{layout}{role_bit} '
        f'Render this exact text into the artwork, spelled precisely, nothing more: '
        f'hero text "{h}"; supporting line "{s}"; data text "{st}". '
        f'Every number must appear exactly as written — never invent, round, or add figures. '
        f'The typography IS the design: obsessive kerning, strong alignment, dramatic size '
        f'hierarchy, phone-readable at thumbnail size. Flat 2D graphic design, no photos, '
        f'no 3D renders, no stock illustrations of people or laptops, no frosted glass cards, '
        f'no fake UI chrome, no watermarks, no extra decorative icons, no additional words. '
        f'Consistent margins as if part of a designed six-slide series from one design system. '
        f'Composition breathes: at least a third of the frame stays empty. '
        f'The result should look like a page from a premium data-driven zine that a design '
        f'studio would post — confident, quiet, exact.'
    )
    return assert_visual_prompt(prompt)
