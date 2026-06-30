from app.agents.review_decision import parse_review_decision

def test_changes_requested_wins_over_approved_examples():
    content = '\n    Changes requested:\n    - Ensure status badges render exact text `Approved` and `Rejected`.\n    '
    assert parse_review_decision(content) == 'changes_requested'

def test_approved_marker_is_approved():
    assert parse_review_decision('Approved: no changes needed.') == 'approved'

def test_empty_review_defaults_to_changes_requested():
    assert parse_review_decision('') == 'changes_requested'