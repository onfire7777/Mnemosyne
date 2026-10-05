from leaderboard.grouping import build_comparison_index
from leaderboard.workspace import comparison_body
from tests.test_leaderboard_grouping import _input


def test_workspace_exposes_provenance_filters_and_reported_uncertainty():
    a, ap = _input('Synthetic Amber')
    b, bp = _input('Synthetic Cedar')
    result = build_comparison_index([a,b], {a['record_id']:ap,b['record_id']:bp})
    html = comparison_body(result)
    assert 'Comparison group' in html and '<legend>Systems</legend>' in html
    assert 'aria-live="polite"' in html
    assert 'data-source="' + result['source_digest'] + '"' in html
    assert '0.6 to 0.85' in html and '95%' not in html
    assert html.index('Synthetic Amber<small>') < html.index('Synthetic Cedar<small>')
    assert 'comparison-index.json' in html
    assert '<noscript>' in html
    assert 'No cross-group ranking' not in html  # Client status is separate from server tables.


def test_workspace_escapes_hostile_system_labels():
    label = '<script>alert(1)</script>'
    record, payloads = _input(label)
    html = comparison_body(build_comparison_index([record], {label:payloads}))
    assert label not in html
    assert '&lt;script&gt;' in html
    assert 'Single system: no competitor comparison yet' in html


def test_workspace_preserves_excluded_record_reason():
    record, _ = _input('Synthetic Missing')
    html = comparison_body(build_comparison_index([record], {}))
    assert 'No compatible result groups' in html
    assert 'Synthetic Missing' in html and 'unverified artifacts' in html
