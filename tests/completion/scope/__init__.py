"""Scope-conformance verification for the two INTENTIONALLY-LIMITED P2 FRs.

This package holds FR-20 (multimodal memory, blueprint non-goal N5 "post-v1")
and FR-21 (parametric/LoRA tier, blueprint non-goal N2 "optional advanced
tier") to their *limited* v1 bar — not a full P2 implementation.

It is deliberately a **forcing function**: every check measures the CURRENT
``src/mnemosyne`` honestly. A check passes only if the limited v1 bar is met,
fails if the substrate regresses below it, and each module documents — in
``REAL_DEPLOYMENT_VALIDATION`` — exactly what real-deployment validation is
correctly DEFERRED (out of scope for v1).

The runner (``run_scope_conformance.py``) is dependency-free (stdlib only) so it
executes under either venv. A pytest shim (``test_scope_conformance.py``) lets
the same assertions run inside the normal ``tests/`` collection.
"""
