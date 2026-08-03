"""Give DIRECTOR access to product vision / reference docs (read-only)."""

from __future__ import annotations

from pathlib import Path

from agents import function_tool

DOCS = Path('/home/user/Documents/documents')
ROOT = Path('/home/user/Documents')

ALLOWED = {
    'prd': DOCS / 'product-requirements-v0.md',
    'roadmap': DOCS / 'roadmap.md',
    'hermes': DOCS / 'hermes-agent-integration.md',
    'remote': DOCS / 'remote-access-cloudflare.md',
    'ux': ROOT / '.cursor' / 'rules' / 'product-ux.mdc',
    'lead': ROOT / '.cursor' / 'rules' / 'akay-lead.mdc',
}


@function_tool
def read_vision_doc(doc: str = 'prd', max_chars: int = 6000) -> str:
    """Read a JobMaster / Watch Tower reference document for vision and purpose.
    doc: prd | roadmap | hermes | remote | ux | lead
    Use when you need north-star language, brand, flywheel, or ops laws."""
    key = (doc or 'prd').strip().lower()
    path = ALLOWED.get(key)
    if not path or not path.exists():
        return f'Unknown or missing doc={doc}. Allowed: {", ".join(ALLOWED)}'
    text = path.read_text(encoding='utf-8', errors='replace')
    if len(text) > max_chars:
        return text[:max_chars] + f'\n\n…[truncated {len(text) - max_chars} chars]'
    return text
