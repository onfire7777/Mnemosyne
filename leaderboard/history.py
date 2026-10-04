"""Render a verified local attempt history without granting publication rights."""
from hashlib import sha256
from html import escape


def _text(value):
    return escape(str(value), quote=True)


def history_body(snapshot: dict | None, records: list[dict]) -> str:
    intro = ('<h1>Every recorded attempt</h1><p class="intro">Successes, failures and missing runs belong in the same history.</p>')
    if snapshot is None:
        return intro + ('<p>No verified signed history has been supplied to this preview. '
                        'An empty results table does not prove that no runs were attempted.</p>'
                        '<p><a href="methods.html">Read the evidence requirements</a></p>')
    present = {record['record_id'] for record in records}
    rows = []
    superseded = {entry['supersedes'] for entry in snapshot['entries'] if entry['status'] == 'superseded'}
    for entry in snapshot['entries']:
        result = entry['result']
        record_id = result['record_id'] if isinstance(result, dict) else None
        evidence = 'No result record'
        if record_id in present:
            evidence = f'<a href="results/{sha256(record_id.encode()).hexdigest()}.html">{_text(record_id)}</a>'
        elif record_id:
            evidence = f'{_text(record_id)} — not included in this results view'
        state = entry['status'] + (' (superseded)' if entry['entry_id'] in superseded else '')
        reason = _text(entry['reason'] or '—')
        if entry['supersedes']:
            reason += f'<br>Supersedes: {_text(entry["supersedes"])}'
        rows.append(f'<tr><th scope="row">{entry["sequence"]}</th><td>{_text(entry["entrant_id"])}</td>'
                    f'<td>{_text(state)}</td><td>{_text(entry["timestamp"])}</td>'
                    f'<td>{reason}</td><td>{evidence}</td></tr>')
    roster = ', '.join(_text(entrant) for entrant in snapshot['roster'])
    return (intro + '<p><strong>Local signed-history preview — not approved for publication.</strong> '
            'Entry signatures, the signed roster and the final ledger head were checked together during rendering. '
            'This verifies the supplied record chain, not independent operation or the truth of every claim.</p>'
            f'<p>Registered entrants: {roster}</p>'
            '<div class="table-scroll" role="region" aria-label="Recorded attempts" tabindex="0"><table>'
            '<thead><tr><th scope="col">Sequence</th><th scope="col">Entrant</th><th scope="col">Outcome</th>'
            '<th scope="col">Recorded time</th><th scope="col">Reason</th><th scope="col">Result</th></tr></thead>'
            '<tbody>' + ''.join(rows) + '</tbody></table></div>'
            '<p><a href="data/attempt-history.json" download>Download signed history snapshot (JSON)</a></p>'
            '<p>The download retains original entry and head signatures and the public key. '
            'Its outer JSON wrapper is not separately signed. It can contain results absent from the visible results table.</p>')
