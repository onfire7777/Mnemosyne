import json
import pytest

from leaderboard.ledger import append_entry
from leaderboard.render import RenderError, render_site
from tests.test_leaderboard_ledger import key_paths as key_paths
from tests.test_leaderboard_render import _result, _trace, _write_json, _write_traces


def _history(tmp_path, private):
    ledger = tmp_path / 'history.jsonl'
    for entrant, status in [('a', 'succeeded'), ('b', 'failed'), ('c', 'no_run')]:
        append_entry(ledger, private, entry_id='entry-'+entrant, timestamp='2026-10-04T12:00:00Z',
                     entrant_id=entrant, status=status, run_id=None if status == 'no_run' else 'run-'+entrant,
                     reason=None if status == 'succeeded' else '<script>reason</script>',
                     result=_result() if status == 'succeeded' else None, roster=['a','b','c'])
    return ledger


def test_history_keeps_all_outcomes_and_signed_roster(tmp_path, key_paths):
    private, public = key_paths
    ledger = _history(tmp_path, private)
    records = _write_json(tmp_path/'results.json', [])
    render_site(records, {}, tmp_path/'site', ledger_source=(ledger,public))
    html = (tmp_path/'site/attempts.html').read_text()
    assert all(state in html for state in ('succeeded','failed','no_run'))
    assert 'Registered entrants: a, b, c' in html
    assert '<script>reason</script>' not in html
    assert '&lt;script&gt;reason&lt;/script&gt;' in html
    assert 'not included in this results view' in html
    assert 'not approved for publication' in html
    snapshot = json.loads((tmp_path/'site/data/attempt-history.json').read_text())
    assert len(snapshot['entries']) == 3
    assert snapshot['publication_authorized'] is False


def test_history_links_only_present_matching_results(tmp_path, key_paths):
    private, public = key_paths
    ledger = _history(tmp_path, private)
    result = _result()
    records = _write_json(tmp_path/'results.json', [result])
    trace = _write_traces(tmp_path/'trace.jsonl', [_trace()])
    render_site(records, {'result-001':trace}, tmp_path/'site', ledger_source=(ledger,public))
    assert 'href="results/' in (tmp_path/'site/attempts.html').read_text()
    result['metrics'][0]['value'] = 0.123
    _write_json(records, [result])
    with pytest.raises(RenderError, match='not present in signed'):
        render_site(records, {'result-001':trace}, tmp_path/'rejected', ledger_source=(ledger,public))
    assert not (tmp_path/'rejected').exists()


def test_history_rejects_bad_signature_before_replacing_site(tmp_path, key_paths):
    private, public = key_paths
    ledger = _history(tmp_path, private)
    records = _write_json(tmp_path/'results.json', [])
    site = tmp_path/'site'
    render_site(records, {}, site)
    before = (site/'attempts.html').read_bytes()
    data = ledger.read_text().replace('run-a','forged')
    ledger.write_text(data)
    with pytest.raises(RenderError, match='invalid attempt history'):
        render_site(records, {}, site, ledger_source=(ledger,public))
    assert (site/'attempts.html').read_bytes() == before
    assert not (site/'data/attempt-history.json').exists()
