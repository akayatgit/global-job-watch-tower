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

URL_RE = re.compile(r'https?://\S+')
WS_RE = re.compile(r'\s+')
SENTENCE_RE = re.compile(r'[.!?;]\s+|\n+')


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


def clean_text(raw: str) -> str:
    """Collapse whitespace, strip URLs and marketplace boilerplate, cap length."""
    text = (raw or '').replace('\r', '\n')
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
    first = re.sub(r'(?i)^(create|generate|make|render|produce)\s+(a|an|the)?\s*', '', first).strip()
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
    # A prompt must be long enough and touch at least camera-or-lighting
    # AND product-or-motion — otherwise it is a caption, not a recipe.
    is_prompt = (
        len(text) >= MIN_PROMPT_CHARS
        and covered >= 3
        and (families.get('camera', 0) or families.get('lighting', 0))
        and (families.get('product', 0) or families.get('motion', 0))
    )
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
