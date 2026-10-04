"""Shared, offline-first presentation shell. No result or admission semantics."""
from html import escape

NAV = (
    ('index.html', 'Results', 'M4 19V10m8 9V5m8 14V2'),
    ('benchmarks.html', 'Benchmarks', 'M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z'),
    ('coverage.html', 'Coverage', 'M4 5h16M4 12h16M4 19h16M8 3v18'),
    ('compare.html', 'Compare runs', 'M8 4v16m8-16v16M4 8h8m0 8h8'),
    ('systems.html', 'Memory systems', 'M12 3l9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5'),
    ('comparisons.html', 'Feature landscape', 'M4 4h16v16H4zM4 10h16M10 4v16'),
    ('attempts.html', 'Attempt history', 'M4 6v5h5M4 11a8 8 0 1 1 2 7M12 7v5l3 2'),
    ('methods.html', 'Methodology', 'M4 4h6l2 2 2-2h6v15h-6l-2 2-2-2H4zM12 6v15'),
)


def icon(path):
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{path}"/></svg>'


def page_shell(title, body, root=''):
    active = {'Development evidence': 'Benchmarks', 'Leaderboard': 'Results', 'Benchmark catalog': 'Benchmarks', 'Whole-memory coverage': 'Coverage',
              'Compare': 'Compare runs', 'Memory systems': 'Memory systems',
              'Capabilities and benchmark coverage': 'Feature landscape', 'Attempt history': 'Attempt history',
              'Methods': 'Methodology'}.get(title, 'Results')
    nav = ''.join(f'<a href="{root}{url}"' + (' aria-current="page"' if label == active else '') +
                  f'>{icon(path)}<span>{label}</span></a>' for url, label, path in NAV)
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(title)} · Mnemetric</title><link rel="stylesheet" href="{root}site.css">'
        f'<script src="{root}site.js" defer></script></head><body>'
        '<a class="skip-link" href="#main-content">Skip to content</a>'
        '<aside class="sidebar" aria-label="Workspace">'
        f'<a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true">m</span>Mnemetric<span class="brand-dot">.</span></a>'
        '<button class="menu-toggle" type="button" aria-expanded="false" aria-controls="workspace-nav" hidden>Explore <span aria-hidden="true">☰</span></button>'
        '<p class="workspace-label">MEMORY INTELLIGENCE</p>'
        f'<nav id="workspace-nav" aria-label="Main">{nav}</nav>'
        '<div class="sidebar-note"><span class="preview-dot"></span> Research preview'
        '<p>Open evidence.<br>Visible limitations.</p>'
        f'<a href="{root}methods.html">How we measure <span aria-hidden="true">↗</span></a></div></aside>'
        '<div class="workspace"><header class="topbar">'
        f'<span class="breadcrumb">Workspace <span aria-hidden="true">/</span> <strong>{escape(active)}</strong></span>'
        f'<a class="subtle-link" href="{root}data/catalog.json" download>Scope data <span aria-hidden="true">↓</span></a></header>'
        f'<main id="main-content" tabindex="-1">{body}</main>'
        '<footer class="site-footer"><span>Evidence for AI memory.</span>'
        '<span>Open, operator-run. Mnemosyne is the operator entry.</span></footer></div></body></html>\n'
    )
