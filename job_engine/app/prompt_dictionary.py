"""Reusable cinematic prompt templates for Grok Imagine (xai/grok-imagine-image).

Ashok locked this style 2026-08-03: detailed, descriptive, logical sentences,
keywords, adjectives, characteristics, action, wow element, aesthetic.
Default mood: aesthetic · calm · bright white · helpful — not memes.

Add new keys to TEMPLATES when Ashok introduces more Carousel looks.
"""

from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {
    'bright_white_calm': {
        'label': 'Bright White Calm (default chat + carousel)',
        'overlay_color': 'soft charcoal grey on luminous white space',
        'overlay_placement': 'centered',
        'quality_tail': (
            'bright airy whites, soft daylight, minimal clutter, '
            'hopeful professional atmosphere for students and seekers'
        ),
    },
}


def fill_cinematic(
    *,
    setting: str,
    environment: str,
    lighting: str,
    subjects: str,
    action: str,
    overlay_text: str = '',
    template_key: str = 'bright_white_calm',
    overlay_placement: str | None = None,
    overlay_color: str | None = None,
    include_overlay: bool = True,
) -> str:
    tpl = TEMPLATES.get(template_key) or TEMPLATES['bright_white_calm']
    if include_overlay and overlay_text.strip():
        overlay_block = (
            f'Overlay text appears elegantly integrated into the scene: the words '
            f'"{overlay_text.strip()[:120]}" {overlay_placement or tpl["overlay_placement"]}, '
            f'displayed in a beautiful natural serif font, {overlay_color or tpl["overlay_color"]}, '
            'refined and organic, positioned subtly within the composition (either centered or '
            'gently floating near the upper third of the frame). The typography is soft, sophisticated, '
            'and harmonious with the calm bright palette, with slight depth and gentle shadowing to '
            'blend into the cinematic environment.'
        )
    else:
        overlay_block = (
            'Do not render any readable text, letters, numbers, watermarks, or logos in the image — '
            'pure visual scene only.'
        )
    body = (
        f'A cinematic, ultra-detailed scene of {setting.strip()}. {environment.strip()}\n'
        f'{lighting.strip()}\n\n'
        f'{subjects.strip()}\n\n'
        f'{action.strip()}\n\n'
        f'{overlay_block}\n\n'
        'Highly detailed, photorealistic lighting, cinematic depth of field, natural color grading, '
        'soft atmospheric perspective, bright white aesthetic, calm helpful mood, sharp foreground '
        'detail, subtle film grain'
    )
    return f"{body}\n{tpl['quality_tail']}"


def scene_for_chat(user_msg: str, helpful_line: str, fact_line: str | None = None) -> str:
    """Calm bright-white reply scene from user intent + helpful truth."""
    topic = (user_msg or 'the TECH job market').strip()[:160]
    overlay = helpful_line.strip()[:90] or 'Watch Tower is with you'
    if fact_line:
        overlay = f'{overlay} · {fact_line.strip()[:40]}'
    return fill_cinematic(
        setting=(
            'a calm, luminous interior atrium of a modern learning campus at soft morning daylight, '
            'bright white stone floors, pale oak and frosted glass, airy and serene'
        ),
        environment=(
            f'The space gently suggests the seeker’s question — "{topic}" — through soft environmental '
            'storytelling: open books on a white table, a distant city skyline through tall clear glass, '
            'potted greens, and quiet pathways. Nothing chaotic; everything ordered, hopeful, and readable.'
        ),
        lighting=(
            'Warm-cool balanced daylight floods the room; soft shadows, gentle bloom on white surfaces, '
            'high-key exposure, ethereal haze in the far distance'
        ),
        subjects=(
            'In the mid-ground, a young graduate (about 20–24) in simple light clothing stands calmly '
            'beside a slim glass railing, posture upright and curious, looking toward the bright city beyond. '
            'Nearby, a minimal white desk holds a single open notebook and a cup of tea — human, grounded, peaceful.'
        ),
        action=(
            'The graduate pauses mid-thought, inhaling hope; a soft breeze moves a curtain of sheer white fabric. '
            'The wow element is a floating translucent holographic map of India hiring lights — subtle cyan points — '
            'hovering quietly above the desk like living data, never garish.'
        ),
        overlay_text=overlay,
        template_key='bright_white_calm',
    )


def scene_for_carousel_slide(
    *,
    slide_key: str,
    headline: str,
    role_hint: str = 'TECH careers',
) -> str:
    """Same cinematic shell for every Carousel background until new templates are added."""
    motifs = {
        'hook': (
            'a vast bright white observatory terrace overlooking a sunlit Indian tech campus',
            'A graduate stands at the edge of a white stone terrace, eyes on the horizon of glass buildings.',
        ),
        'pulse': (
            'an airy data library with white shelves and soft holographic charts floating like lanterns',
            'Gentle light particles form rising curves of openings — calm evidence, not alarm.',
        ),
        'rising': (
            'a bright hillside path of pale stone leading upward between white flowering trees',
            'A figure walks upward with quiet confidence toward a glass pavilion glowing in daylight.',
        ),
        'hirer': (
            'a luminous corporate campus courtyard with white paving and soft green lawns',
            'Glass office facades reflect the sky; doors of opportunity appear open, never threatening.',
        ),
        'fresher': (
            'a bright university quad with white colonnades and students walking in soft morning light',
            'Young seekers gather calmly around a circular fountain of clear water.',
        ),
        'cta': (
            'a serene white hall with a single open doorway filled with warm daylight',
            'A graduate steps toward the light, hopeful and composed.',
        ),
        'topic-hook': (
            f'a bright white briefing room dedicated to {role_hint}',
            'Clean glass boards and soft maps frame the conversation without clutter.',
        ),
        'date': (
            'a calm white studio with a large window and soft calendar light on the wall',
            'Time feels clear and present; nothing rushed.',
        ),
        'companies': (
            'an elegant bright atrium where company name plates appear as soft frosted glass panels',
            'Panels catch daylight; the space feels curated and trustworthy.',
        ),
        'more': (
            'a longer white gallery corridor lined with soft frosted plaques',
            'The viewer walks forward calmly, discovering more names in sequence.',
        ),
        'default': (
            'a calm bright white architectural space with soft daylight and gentle greenery',
            'A thoughtful graduate stands present, open, and at peace with the facts.',
        ),
    }
    setting_core, action_core = motifs.get(slide_key, motifs['default'])
    return fill_cinematic(
        setting=setting_core,
        environment=(
            f'The composition supports the Carousel idea "{headline}" with clear spatial logic, '
            'readable depth, and a wow element of soft floating light motes that feel intelligent but serene.'
        ),
        lighting=(
            'High-key soft daylight, bright whites, gentle shadows, cinematic depth of field, natural color grading'
        ),
        subjects=(
            'A young professional in light natural fabrics stands or sits calmly in the scene; '
            'expression curious and hopeful; hair and cloth move slightly in a soft breeze.'
        ),
        action=action_core,
        include_overlay=False,
        template_key='bright_white_calm',
    )
