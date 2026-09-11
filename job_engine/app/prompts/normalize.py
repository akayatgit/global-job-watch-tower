"""Deterministic reading of a candidate video prompt.

Nothing here asks a model. These functions decide whether a block of text
is even a video prompt, fingerprint it for exact dedupe, guess the target
model and product category from literal vocabulary, and produce the
heuristic pre-score that anchors the Hermes score (so an LLM can never be
the only voice behind a number).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

MIN_PROMPT_CHARS = 180
MAX_PROMPT_CHARS = 6000

# Vocabulary a real production-grade video prompt uses. Each family is
# counted once — depth in many families beats repetition in one.
VOCAB_FAMILIES: dict[str, tuple[str, ...]] = {
    'camera': (
        'camera', 'lens', 'mm', 'shutter', 'iso', 'aperture', 'f/', 'dolly',
        'pan', 'tilt', 'tracking shot', 'close-up', 'closeup', 'macro',
        'wide shot', 'orbit', 'push-in', 'push in', 'pull back', 'gimbal',
        'handheld', 'slow motion', 'slow-motion', 'fps', 'depth of field', 'bokeh',
    ),
    'lighting': (
        'light', 'lighting', 'shadow', 'rim light', 'key light', 'backlit',
        'softbox', 'golden hour', 'studio', 'reflection', 'reflections',
        'caustics', 'glow', 'highlight', 'white balance', 'kelvin', ' k ',
    ),
    'material': (
        'glass', 'metal', 'matte', 'glossy', 'texture', 'liquid', 'droplet',
        'condensation', 'fabric', 'ceramic', 'wood', 'marble', 'chrome', 'satin',
        'translucent', 'transparent', 'frosted',
    ),
    'motion': (
        'rotate', 'rotating', 'spin', 'float', 'floating', 'rise', 'falls',
        'pour', 'splash', 'ripple', 'swirl', 'drift', 'reveal', 'transition',
        'morph', 'settle', 'burst', 'unfold', 'slowly', 'gently',
    ),
    'format': (
        '9:16', '16:9', '1:1', '4:5', 'vertical', 'seconds', 'second', 'sec',
        '4k', '1080', 'photorealistic', 'cgi', 'commercial', 'ad', 'reel',
    ),
    'product': (
        'product', 'bottle', 'packaging', 'label', 'logo', 'brand', 'cap',
        'jar', 'tube', 'can', 'box', 'sneaker', 'shoe', 'watch', 'perfume',
        'fragrance', 'serum', 'cream', 'lipstick', 'coffee', 'tea', 'drink',
        'beverage', 'snack', 'candle', 'headphones', 'phone', 'laptop', 'bag',
    ),
    'constraints': (
        'preserve', 'exact', 'do not', "don't", 'never', 'keep', 'strict',
        'consistent', 'no text', 'no watermark', 'accurate', 'faithful',
    ),
}

MODEL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('veo', ('veo 3', 'veo3', 'veo-3', 'google veo', 'veo')),
    ('kling', ('kling',)),
    ('sora', ('sora',)),
    ('runway', ('runway', 'gen-3', 'gen-4', 'gen3', 'gen4')),
    ('luma', ('luma', 'dream machine')),
    ('pika', ('pika',)),
    ('hailuo', ('hailuo', 'minimax')),
    ('wan', ('wan 2', 'wan2', 'wan-2')),
    ('seedance', ('seedance',)),
    ('midjourney', ('midjourney',)),
)

CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('perfume', ('perfume', 'fragrance', 'eau de', 'cologne', 'scent')),
    ('skincare', ('serum', 'moisturizer', 'moisturiser', 'skincare', 'cream', 'sunscreen', 'cleanser', 'lotion')),
    ('makeup', ('lipstick', 'mascara', 'foundation', 'makeup', 'eyeliner', 'blush')),
    ('beverage', ('coffee', 'tea', 'juice', 'soda', 'beer', 'wine', 'drink', 'beverage', 'energy drink', 'water bottle', 'cold brew')),
    ('food', ('chocolate', 'snack', 'cookie', 'protein bar', 'candy', 'ice cream', 'cereal', 'burger', 'pizza')),
    ('footwear', ('sneaker', 'shoe', 'boot', 'sandal', 'footwear', 'trainer')),
    ('fashion', ('jacket', 'dress', 'hoodie', 't-shirt', 'tshirt', 'denim', 'saree', 'kurta', 'apparel', 'handbag', 'bag')),
    ('jewellery', ('ring', 'necklace', 'earring', 'bracelet', 'jewellery', 'jewelry', 'gold', 'diamond')),
    ('tech', ('headphones', 'earbuds', 'smartphone', 'phone', 'laptop', 'smartwatch', 'speaker', 'camera body', 'gadget')),
    ('home', ('candle', 'sofa', 'lamp', 'furniture', 'mug', 'cookware', 'pan', 'kettle', 'diffuser')),
    ('supplements', ('supplement', 'vitamin', 'protein powder', 'whey', 'gummies', 'capsule')),
    ('automotive', ('car', 'motorcycle', 'bike', 'ev', 'scooter', 'tyre', 'tire')),
    ('toys', ('toy', 'lego', 'plush', 'puzzle')),
)

# Product words that must appear as whole words for the D2C gate. The
# family counter above is substring-based (fine for scoring), but 'can'
# inside "candle"/"scan", 'cap' inside "capture", 'ad' inside "shadow" made
# samurai and stadium scenes pass as product videos (2026-09-10 audit).
WEAK_PRODUCT_WORDS = frozenset({'can', 'cap', 'ad', 'box', 'bag'})
PRODUCT_WORD_RE = re.compile(
    r'(?<![a-z0-9])(' + '|'.join(
        re.escape(w) for w in VOCAB_FAMILIES['product'] if w not in WEAK_PRODUCT_WORDS
    ) + r')s?(?![a-z0-9])'
)
# "[product]" / "[camera movement]" slots — a template, not a prompt. One
# or two slots (e.g. "[brand]") are fine; three or more is a fill-in form.
PLACEHOLDER_RE = re.compile(r'\[[^\[\]\n]{2,40}\]')
MAX_PLACEHOLDERS = 2
CJK_RE = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]')
MAX_CJK_RATIO = 0.15

# Blog / README prose ABOUT prompting name-drops camera, lighting and
# product too, so vocabulary alone let "How does each block change the
# output?" and FAQ answers through (2026-09-10 six-source probe). A finished
# prompt describes a shot; it does not explain, advise, or ask.
PROSE_HARD_RE = re.compile(
    r'(?i)(?<![a-z])(?:'
    r'use this when|this (?:guide|article|checklist|pack|post|template)|'
    r'frequently asked|faq|how to write|step \d|table of contents|read more|'
    r'subscribe|sign up|click here|try it (?:now|free)|what (?:the|a|your|it) |'
    r'\d+\s*-\s*\d+s:\s*(?:hook|demo|proof|cta)\b'
    r')'
)
# Constraint words a real prompt uses ("should", "avoid", "keep") and
# product vocabulary ("model", "notes", "gives a soft glow") are NOT here on
# purpose — only words that explain, advise, or address a reader.
PROSE_STRONG_RE = re.compile(
    r"(?i)(?<![a-z])(?:"
    r"prompts?|prompting|guides?|articles?|checklists?|formulas?|workflows?|"
    r"generators?|ai video|purpose:|variants?|structure|approach|teams?|"
    r"founders?|sellers?|shoppers?|media buyers?|paid traffic|target audience|"
    r"dtc|d2c|shopify|amazon|google|outputs?|fps|examples?|e\.g\.|such as|"
    r"for example|usually|often|because|if you|if the|when you|instead|"
    r"rather than|not just|skip|works best|tends? to|helps?|useful|matters?|"
    r"decides?|enough to|yes\."
    r")(?![a-z])"
)
PROSE_WEAK_RE = re.compile(
    r'(?i)(?<![a-z])(?:veo|kling|sora|runway|midjourney|pika|luma|hailuo|seedance)(?![a-z])'
)
QUESTION_RE = re.compile(r'\?')

URL_RE = re.compile(r'https?://\S+')
WS_RE = re.compile(r'\s+')
SENTENCE_RE = re.compile(r'[.!?;]\s+|\n+')
MD_LINK_RE = re.compile(r'\[([^\]]*)\]\((?:[^)\s]+)(?:\s+"[^"]*")?\)')
MD_IMAGE_RE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
MD_NOISE_LINE_RE = re.compile(
    r'^\s*(?:'
    r'#{1,6}\s.*'                         # headings
    r'|(?:-{3,}|\*{3,}|_{3,})\s*'         # horizontal rules
    r'|\|.*\|\s*'                         # table rows
    r'|(?:`[^`]*`\s*(?:[·•|,]\s*)?)+'     # tag lines: `6s · 9:16` · `skincare`
    r'|\*{0,2}\[?[⬆▶►→↑]\s.*'             # nav / CTA lines
    r'|>\s*💡.*'                          # callout tips
    r')$'
)


@dataclass
class PromptReading:
    text: str
    fingerprint: str
    is_prompt: bool
    heuristic_score: float
    model_hint: str | None
    category: str | None
    title: str
    families: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def strip_markdown(raw: str) -> str:
    """Drop README chrome (headings, nav links, tag lines, tables) and
    unwrap inline links/emphasis. Bracket slots like "[brand]" survive."""
    text = MD_IMAGE_RE.sub('', raw or '')
    text = MD_LINK_RE.sub(r'\1', text)
    kept: list[str] = []
    for line in text.split('\n'):
        if MD_NOISE_LINE_RE.match(line):
            kept.append('')
            continue
        line = re.sub(r'\*\*(.*?)\*\*', r'\1', line)
        line = re.sub(r'(?<!\w)\*(?!\s)(.*?)\*(?!\w)', r'\1', line)
        line = re.sub(r'^\s*>\s?', '', line)
        line = re.sub(r'`([^`]*)`', r'\1', line)
        kept.append(line)
    return '\n'.join(kept)


def product_word_hits(text: str) -> int:
    return len(PRODUCT_WORD_RE.findall((text or '').lower()))


def placeholder_count(text: str) -> int:
    return len(PLACEHOLDER_RE.findall(text or ''))


def cjk_ratio(text: str) -> float:
    letters = [c for c in (text or '') if not c.isspace()]
    if not letters:
        return 0.0
    return len(CJK_RE.findall(''.join(letters))) / len(letters)


def looks_like_prose(text: str) -> bool:
    """True when the block explains prompting instead of being a prompt.

    Hard markers ("use this when", FAQ, "0-2s: Hook —" outlines) reject on
    their own. Otherwise reader-facing vocabulary is counted: two hits in a
    short block, two hits plus a model name-drop, or three hits anywhere is
    prose. A question mark is prose too unless the block is long dialogue
    with no meta vocabulary (UGC scripts may ask "have you tried this?").
    """
    body = text or ''
    if PROSE_HARD_RE.search(body):
        return True
    strong = len(PROSE_STRONG_RE.findall(body))
    weak = len(PROSE_WEAK_RE.findall(body))
    words = len(body.split())
    if strong >= 3:
        return True
    if strong >= 2 and (weak >= 1 or words < 120):
        return True
    if QUESTION_RE.search(body) and (strong >= 1 or words < 60):
        return True
    return False


def clean_text(raw: str) -> str:
    """Collapse whitespace, strip URLs and marketplace boilerplate, cap length."""
    text = strip_markdown((raw or '').replace('\r', '\n'))
    text = URL_RE.sub('', text)
    # Common "engagement bait" lines around reposted prompts
    text = re.sub(
        r'(?im)^\s*(comment|dm|follow|like|save|share)\b[^\n]{0,80}$', '', text,
    )
    text = re.sub(r'(?i)\bprompt\s*:\s*', '', text, count=1)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = '\n'.join(line.strip() for line in text.split('\n')).strip()
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text[:MAX_PROMPT_CHARS]


def fingerprint(text: str) -> str:
    norm = WS_RE.sub(' ', (text or '').lower())
    norm = re.sub(r'[^a-z0-9 ]+', '', norm).strip()
    return hashlib.sha1(norm.encode('utf-8')).hexdigest()


def _count_families(low: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    padded = f' {low} '
    for family, words in VOCAB_FAMILIES.items():
        hits = 0
        for word in words:
            if word in padded:
                hits += 1
        counts[family] = hits
    return counts


def detect_model_hint(text: str) -> str | None:
    low = (text or '').lower()
    for name, needles in MODEL_HINTS:
        for needle in needles:
            if re.search(r'(?<![a-z0-9])' + re.escape(needle) + r'(?![a-z0-9])', low):
                return name
    return None


def detect_category(text: str) -> str | None:
    low = f' {(text or "").lower()} '
    best: tuple[int, str] | None = None
    for name, needles in CATEGORIES:
        hits = sum(
            1 for needle in needles
            if re.search(r'(?<![a-z])' + re.escape(needle) + r'(?![a-z])', low)
        )
        if hits and (best is None or hits > best[0]):
            best = (hits, name)
    return best[1] if best else None


def make_title(text: str, category: str | None) -> str:
    """Short human title for Telegram rows: first clause, capped."""
    first = SENTENCE_RE.split((text or '').strip(), maxsplit=1)[0]
    first = re.sub(r'(?i)^(create|generate|make|render|produce)\s+(?:(?:an|a|the)\s+)?', '', first).strip()
    first = first.strip(' ,-–—:')
    if len(first) > 72:
        first = first[:69].rsplit(' ', 1)[0] + '…'
    if not first:
        first = (category or 'video').title() + ' prompt'
    return first[:1].upper() + first[1:]


def heuristic_score(text: str) -> tuple[float, dict[str, int], list[str]]:
    """0–100 from literal structure. Anchors the AI score; never replaces it.

    Points: family coverage (up to 56), length sweet spot (up to 24),
    numeric specificity (up to 12), sentence flow (up to 8).
    """
    low = (text or '').lower()
    families = _count_families(low)
    reasons: list[str] = []

    coverage = 0.0
    for family, hits in families.items():
        # 2 hits saturate a family (8 pts) — 7 families → 56
        coverage += min(hits, 2) * 4
        if hits == 0:
            reasons.append(f'no {family} vocabulary')
    coverage = min(coverage, 56.0)

    n = len(text or '')
    if n < MIN_PROMPT_CHARS:
        length_pts = 0.0
        reasons.append('too short for a production prompt')
    elif n < 400:
        length_pts = 10.0
    elif n <= 2200:
        length_pts = 24.0
    elif n <= 3500:
        length_pts = 16.0
    else:
        length_pts = 8.0
        reasons.append('very long — risk of contradictions')

    numbers = len(re.findall(r'\d+(?:\.\d+)?', text or ''))
    numeric_pts = min(numbers, 6) * 2.0
    if numbers == 0:
        reasons.append('no numeric specifics (mm, fps, seconds, K)')

    sentences = [s for s in SENTENCE_RE.split(text or '') if s.strip()]
    if len(sentences) >= 4:
        flow_pts = 8.0
    elif len(sentences) >= 2:
        flow_pts = 4.0
    else:
        flow_pts = 0.0
        reasons.append('single run-on sentence — weak shot flow')

    score = round(min(100.0, coverage + length_pts + numeric_pts + flow_pts), 1)
    return score, families, reasons


def read_prompt(raw: str) -> PromptReading:
    text = clean_text(raw)
    score, families, reasons = heuristic_score(text)
    model_hint = detect_model_hint(text)
    category = detect_category(text)
    covered = sum(1 for hits in families.values() if hits)
    # A prompt must be long enough, touch camera-or-lighting, and be ABOUT
    # a product (category detected, or a whole-word product noun) — Ashok
    # 2026-09-10: samurai / eagle / stadium scenes are not D2C videos.
    # Fill-in templates ("[product] ... [camera movement]") and non-English
    # index pages are not prompts either.
    has_product = category is not None or product_word_hits(text) > 0
    prose = looks_like_prose(text)
    is_prompt = (
        len(text) >= MIN_PROMPT_CHARS
        and covered >= 3
        and (families.get('camera', 0) or families.get('lighting', 0))
        and has_product
        and placeholder_count(text) <= MAX_PLACEHOLDERS
        and cjk_ratio(text) <= MAX_CJK_RATIO
        and not prose
    )
    if not has_product:
        reasons.append('no product — not a D2C video prompt')
    if placeholder_count(text) > MAX_PLACEHOLDERS:
        reasons.append('fill-in template, not a finished prompt')
    if prose:
        reasons.append('explainer prose about prompting, not a prompt')
    return PromptReading(
        text=text,
        fingerprint=fingerprint(text),
        is_prompt=bool(is_prompt),
        heuristic_score=score,
        model_hint=model_hint,
        category=category,
        title=make_title(text, category),
        families=families,
        reasons=reasons,
    )
