from __future__ import annotations

def parse_review_decision(content: str) -> str:
    """Return the binary reviewer decision from a free-form review response."""
    normalized = content.strip().lower()
    if not normalized:
        return 'changes_requested'
    first_line = next((line.strip() for line in normalized.splitlines() if line.strip()), '')
    if first_line.startswith('changes requested'):
        return 'changes_requested'
    if first_line.startswith('approved'):
        return 'approved'
    if 'changes requested' in normalized:
        return 'changes_requested'
    if 'approved' in normalized:
        return 'approved'
    return 'changes_requested'