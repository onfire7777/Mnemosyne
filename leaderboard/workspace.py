"""Accessible static comparison tables with optional local filtering."""
from hashlib import sha256
from html import escape
import json


def _text(value):
    return escape(str(value), quote=True)


def comparison_body(index: dict) -> str:
    groups = index['groups']
    systems = sorted({system for group in groups for system in group['systems']})
    options = '<option value="">All compatible groups</option>'
    sections = []
    for group in groups:
        key = group['compatibility']
        label = f"{key['benchmark_id']} {key['benchmark_version']} · {key['metric']['name']} · {key['division']} · {group['group_id'][:8]}"
        group_id = group['group_id']
        options += f'<option value="{group_id}">{_text(label)}</option>'
        rows = []
        for row in sorted(group['rows'], key=lambda row: (row['identity']['system_id'], row['record_id'])):
            identity, metric = row['identity'], row['metric']
            interval = metric.get('confidence_interval')
            interval_text = ('Not estimated (descriptive)' if 'summary_kind' in metric else 'Not supplied') if interval is None else f"{interval['low']} to {interval['high']}"
            path = sha256(row['record_id'].encode()).hexdigest()
            rows.append(f'<tr data-system="{_text(identity["system_id"])}">'
                        f'<th scope="row">{_text(identity["system_id"])}<small>{_text(identity["system_version"])}</small></th>'
                        f'<td>{_text(metric["value"])} {_text(metric["unit"])}</td>'
                        f'<td>{_text(interval_text)}</td>'
                        f'<td>{_text(identity["backend_id"])}<small>Hardware: {_text(identity["hardware_fingerprint"])}</small></td>'
                        f'<td><a href="results/{path}.html">{_text(row["record_id"])}</a>'
                        f'<small>Run {_text(identity["run_id"])} · attempt {_text(identity["attempt_id"])} · seed {_text(identity["seed"])}</small></td></tr>')
        status = 'Multiple systems recorded' if group['multi_system'] else 'Single system: no competitor comparison yet'
        sections.append(f'<section class="comparison-group" data-group="{group_id}" aria-labelledby="g-{group_id}">'
                        f'<h2 id="g-{group_id}">{_text(label)}</h2><p>{status}. '
                        f'Track: {_text(key["track_kind"])}. Resource profile: {_text(key["resource_profile"])}.</p>'
                        '<div class="table-scroll" role="region" aria-label="Comparable result rows" tabindex="0">'
                        '<table><thead><tr><th scope="col">System</th><th scope="col">Result</th>'
                        '<th scope="col">Reported interval</th><th scope="col">Execution</th>'
                        '<th scope="col">Evidence</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
                        '<details><summary>Exact comparison conditions</summary>'
                        f'<pre>{_text(json.dumps(key, sort_keys=True, indent=2))}</pre></details></section>')
    checks = ''.join(f'<label><input type="checkbox" name="system" value="{_text(system)}" checked> {_text(system)}</label>' for system in systems)
    exclusions = ''.join(f'<li><a href="results/{sha256(row["record_id"].encode()).hexdigest()}.html">{_text(row["record_id"])}</a>: '
                         f'{_text(row.get("metric", ""))} {_text(row["reason"].replace("-", " "))}</li>' for row in index['exclusions'])
    controls = (f'<form id="comparison-controls" data-source="{_text(index["source_digest"])}" hidden><label for="comparison-group">Comparison group</label>'
                f'<select id="comparison-group">{options}</select>'
                f'<fieldset><legend>Systems</legend>{checks or "<p>No eligible systems yet.</p>"}</fieldset>'
                '<button type="button" id="comparison-reset">Reset filters</button></form>'
                '<p id="comparison-status" role="status" aria-live="polite"></p>')
    return ('<h1>Compare memory evidence</h1>'
            '<p class="intro">Matching conditions. Visible limitations. Every run traceable.</p>'
            '<div class="prose"><p>These groups match declared benchmark, dataset, scoring, model and resource conditions. '
            'They are candidates for inspection, not certified rankings. Each row is one attempt; no overall winner or average is calculated. '
            'Reported intervals retain their original meaning and do not imply a confidence level.</p></div>'
            + controls + '<noscript><p>All groups and systems are shown. JavaScript is optional for filtering.</p></noscript>'
            + (''.join(sections) or '<p>No compatible result groups are available yet. '
               'Missing measurements are not zero scores. <a href="benchmarks.html">Explore planned benchmarks</a>.</p>')
            + '<h2 class="section-heading">Outside comparison groups</h2>'
            + ('<ul>' + exclusions + '</ul>' if exclusions else '<p>No excluded records in this dataset.</p>')
            + '<p><a href="data/comparison-index.json" download>Download comparison data and source IDs (JSON)</a></p>'
            + f'<p><small>Dataset fingerprint: {_text(index["source_digest"])}</small></p>'
            + '<script src="comparison.js" defer></script>')
