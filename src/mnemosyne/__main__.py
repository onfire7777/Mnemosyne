"""Package entry point so Mnemosyne runs without its console scripts.

Installing the distribution creates the ``mneme`` and ``mneme-mcp`` executables,
but a source checkout, a vendored copy or a wheel unpacked onto ``PYTHONPATH``
has no ``Scripts``/``bin`` shims. ``python -m mnemosyne`` is the fallback that
always exists, and it dispatches to exactly the same CLI, so::

    python -m mnemosyne mcp-serve --transport streamable-http

is equivalent to::

    mneme mcp-serve --transport streamable-http

``python -m mnemosyne.mcp_server`` remains available for the raw server
arguments.
"""

from __future__ import annotations

from mnemosyne.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
