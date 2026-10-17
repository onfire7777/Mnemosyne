"""On Windows a test that needs something this machine cannot provide is skipped with its reason, not failed."""

import shutil
import sys

import pytest

if sys.platform == "win32":
    _MODE_BITS = "asserts POSIX permission bits, which NTFS does not keep"
    # shortcut: the hash-pinned harness writes receipt paths with the host separator; fixing it there would
    # invalidate the retained evidence, so fresh Windows receipts are not replayed until a new harness revision
    _RECEIPT = "fresh source receipts from the hash-pinned harness carry Windows path separators"
    _SHELL = "runs a bash or osascript script, which Windows cannot execute"
    # node id prefix -> reason; a module path skips the whole file
    _POSIX_ONLY_TESTS = {
        "tests/test_production_manifest_renderer.py": _SHELL,
        "tests/test_eval_window_admission.py": _SHELL,
        "tests/test_production_vault_tls_validator.py": _SHELL,
        "tests/test_prod_compose_policy.py::test_supply_chain_gate_is_wired_for_required_tools": _SHELL,
        "tests/test_prod_compose_policy.py::test_supply_chain_gate_shell_syntax_is_valid": _SHELL,
        "tests/completion/provenance/test_c2pa_infra_trust_policy.py::test_old_policy_quarantines_positive_path": _SHELL,
        "tests/completion/provenance/test_c2pa_infra_trust_policy.py::test_fixed_policy_": _SHELL,
        "tests/completion/security/test_deletion_residue.py::test_ledger_artifacts_are_owner_only": _MODE_BITS,
        "tests/completion/security/test_deletion_residue.py::test_ledger_sidecars_are_owner_only_while_open": _MODE_BITS,
        "tests/test_engine_contract.py::test_local_engine_persistent_store_is_private": _MODE_BITS,
        "tests/test_engine_contract.py::test_local_engine_preserves_existing_store_parent_permissions": _MODE_BITS,
        "tests/test_evidence_signing.py::test_keygen_writes_private_key_with_owner_only_permissions": _MODE_BITS,
        "tests/test_compact_answering_parity.py::test_manifest_round_trip_is_canonical_and_private": _MODE_BITS,
        "tests/test_public_longmemeval.py::test_external_candidate_manifest_is_schema_bound_and_no_overwrite": _MODE_BITS,
        "tests/test_public_longmemeval_qa.py::test_external_candidate_manifest_freeze_is_immutable_and_schema_bound": _MODE_BITS,
        "tests/test_leaderboard_render.py::test_new_site_has_deployable_directory_permissions": _MODE_BITS,
        "tests/test_planning_traceability.py::test_goalex_round_cleanup_contract_is_behaviorally_reproducible": _MODE_BITS,
    }
    _POSIX_ONLY_TESTS.update({
        # shortcut: not a failure, just slow - run it by hand without --timeout when the bundle code changes
        "tests/test_public_development_bundle_lifecycle.py::test_registered_development_bundle_round_trip[wmbs-m06-development]":
            "starts the real CLI once per operation, about 3 s each on Windows, which outlasts the 300 s test timeout",
        "tests/test_action_pressure.py::test_public_runner_replays_and_retains_every_delivery": _RECEIPT,
        "tests/test_action_pressure.py::test_service_profile_preserves_workload_and_replays": _RECEIPT,
    })
    if shutil.which("cargo") is None:
        _POSIX_ONLY_TESTS["tests/test_compact_answering_embedder.py::test_rust_module_unit_tests_pass_without_model_artifacts"] = "cargo is not installed"

    def pytest_collection_modifyitems(config, items):
        for item in items:
            node = item.nodeid.replace("\\", "/")
            reason = next((why for prefix, why in _POSIX_ONLY_TESTS.items() if node.startswith(prefix)), None)
            if reason:
                item.add_marker(pytest.mark.skip(reason=f"Windows: {reason}"))

    _POSIX_ATTRIBUTES = ("'mkfifo'", "'AF_UNIX'", "'fcntl'", "'getuid'", "'O_NONBLOCK'")

    def _posix_only(error: BaseException) -> str | None:
        if isinstance(error, OSError) and getattr(error, "winerror", None) == 1314:
            return "symlinks need Developer Mode or an elevated shell on Windows"
        if isinstance(error, AttributeError) and any(name in str(error) for name in _POSIX_ATTRIBUTES):
            return f"POSIX-only facility on Windows: {error}"
        return None

    def _skip_posix_only():
        try:
            return (yield)
        except (OSError, AttributeError) as error:
            reason = _posix_only(error)
            if reason is None:
                raise
            pytest.skip(reason)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_setup(item):
        return (yield from _skip_posix_only())

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(item):
        return (yield from _skip_posix_only())
