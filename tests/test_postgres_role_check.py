"""postgres-role-check: live role-separation probe and evidence shape.

The probes run against fakes here; real-infrastructure captures remain
operator-run through the production evidence path (roles.sql mandates the
live probe per prod DSN — this suite pins the probe's SQL contract and the
command's fail-closed evidence shape without needing a cluster).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from typing import Any

import pytest

from mnemosyne.cli import (
    POSTGRES_ROLE_CHECK_REQUIRED_CHECKS,
    _postgres_role_target,
    _probe_postgres_role_connection,
    cmd_postgres_role_check,
)

GROUPS = ("mnemosyne_app", "mnemosyne_consolidator", "mnemosyne_readonly")
GROUP_POSTURE_ROWS = [
    ("mnemosyne_app", False, False, False),
    ("mnemosyne_consolidator", False, False, False),
    ("mnemosyne_readonly", False, False, False),
]


class ScriptedCursor:
    """Returns scripted results keyed by a substring of the executed SQL."""

    def __init__(self, script: dict[str, Any]):
        self.script = script
        self._current: Any = None
        self.statements: list[str] = []

    def __enter__(self) -> ScriptedCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | None = None) -> None:
        normalized = " ".join(sql.split())
        self.statements.append(normalized)
        for token, result in self.script.items():
            if token in normalized:
                self._current = result
                return
        raise AssertionError(f"unscripted SQL: {normalized}")

    def fetchone(self) -> Any:
        return self._current

    def fetchall(self) -> Any:
        return self._current


class ScriptedConnection:
    def __init__(self, script: dict[str, Any]):
        self.script = script

    def cursor(self) -> ScriptedCursor:
        return ScriptedCursor(self.script)


def role_script(
    *,
    current_user: str = "app_user",
    rolsuper: bool = False,
    rolbypassrls: bool = False,
    group_exists: bool = True,
    group_member: bool = True,
    table_rows: list[tuple[str, bool, bool, bool]] | None = None,
    posture_rows: list[tuple[str, bool, bool, bool]] | None = None,
) -> dict[str, Any]:
    if table_rows is None:
        # (tablename, can_delete, can_truncate, can_update)
        table_rows = [
            ("audit_log", False, False, False),
            ("memories", False, False, True),
        ]
    return {
        "FROM pg_roles WHERE rolname = current_user": (current_user, rolsuper, rolbypassrls),
        "pg_has_role": (group_exists, group_member),
        "FROM pg_tables": table_rows,
        "rolcanlogin": posture_rows if posture_rows is not None else GROUP_POSTURE_ROWS,
    }


def test_probe_reports_safe_app_role_posture() -> None:
    conn = ScriptedConnection(role_script())

    probe = _probe_postgres_role_connection(
        conn,
        expected_group="mnemosyne_app",
        group_names=GROUPS,
        audit_table="audit_log",
    )

    assert probe["current_user"] == "app_user"
    assert probe["rolsuper"] is False
    assert probe["rolbypassrls"] is False
    assert probe["group_exists"] is True
    assert probe["group_member"] is True
    assert probe["table_count"] == 2
    assert probe["delete_tables"] == []
    assert probe["truncate_tables"] == []
    assert probe["audit_table_present"] is True
    assert probe["audit_update"] is False
    assert set(probe["groups"]) == set(GROUPS)


def test_probe_surfaces_privileged_and_destructive_posture() -> None:
    conn = ScriptedConnection(
        role_script(
            current_user="postgres",
            rolsuper=True,
            rolbypassrls=True,
            table_rows=[
                ("audit_log", True, False, True),
                ("memories", True, True, True),
            ],
        )
    )

    probe = _probe_postgres_role_connection(
        conn,
        expected_group="mnemosyne_app",
        group_names=GROUPS,
        audit_table="audit_log",
    )

    assert probe["rolsuper"] is True
    assert probe["rolbypassrls"] is True
    assert probe["delete_tables"] == ["audit_log", "memories"]
    assert probe["truncate_tables"] == ["memories"]
    assert probe["audit_delete"] is True
    assert probe["audit_update"] is True


def test_postgres_role_target_redacts_dsn_and_flags_local() -> None:
    remote = _postgres_role_target("postgresql://app_user@postgres.internal.example.com:5432/mnemosyne")
    assert remote["host"] == "postgres.internal.example.com"
    assert remote["port"] == 5432
    assert remote["dbname"] == "mnemosyne"
    assert remote["local"] is False
    assert remote["dsn_sha256"].startswith("sha256:")
    assert "dsn" not in remote

    assert _postgres_role_target("postgresql://app_user@localhost/mnemosyne")["local"] is True
    assert _postgres_role_target("postgresql://app_user@127.0.0.1/mnemosyne")["local"] is True
    keyvalue = _postgres_role_target("host=postgres.internal.example.com port=5432 dbname=mnemosyne")
    assert keyvalue["local"] is False
    assert keyvalue["dbname"] == "mnemosyne"
    # Ambiguous DSNs (no parseable host) must fail closed as local.
    assert _postgres_role_target("dbname=mnemosyne")["local"] is True


def make_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "app_dsn": "postgresql://app_user@postgres.internal.example.com:5432/mnemosyne",
        "consolidator_dsn": "postgresql://consolidator_user@postgres.internal.example.com:5432/mnemosyne",
        "expected_app_group": "mnemosyne_app",
        "expected_consolidator_group": "mnemosyne_consolidator",
        "readonly_group": "mnemosyne_readonly",
        "audit_table": "audit_log",
        "app_fk_cascade_delete_tables": "justifications,contradictions",
        "connect_timeout": 5,
        "allow_localhost": False,
        "expected_fingerprint": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def install_fake_psycopg(monkeypatch: pytest.MonkeyPatch, scripts_by_user: dict[str, dict[str, Any]]) -> None:
    class FakePsycopgModule:
        @staticmethod
        @contextlib.contextmanager
        def connect(dsn: str, *, autocommit: bool = False, connect_timeout: int = 0) -> Any:
            for user, script in scripts_by_user.items():
                if f"{user}@" in dsn:
                    yield ScriptedConnection(script)
                    return
            raise AssertionError(f"unscripted DSN: {dsn}")

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopgModule())


def consolidator_script() -> dict[str, Any]:
    return role_script(
        current_user="consolidator_user",
        table_rows=[
            ("audit_log", False, False, False),
            ("memories", True, False, True),
        ],
    )


def test_cmd_postgres_role_check_passes_on_separated_roles(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_psycopg(
        monkeypatch,
        {"app_user": role_script(), "consolidator_user": consolidator_script()},
    )

    cmd_postgres_role_check(make_args())

    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["findings"] == []
    check_names = {check["name"] for check in report["checks"]}
    assert check_names == set(POSTGRES_ROLE_CHECK_REQUIRED_CHECKS)
    assert all(check["ok"] is True for check in report["checks"])
    assert report["roles"]["app"]["rolsuper"] is False
    assert report["roles"]["consolidator"]["current_user"] == "consolidator_user"
    assert len(report["fingerprint"]) == 64
    assert report["target"]["app"]["dsn_sha256"].startswith("sha256:")
    assert "dsn" not in report["target"]["app"]


def test_cmd_postgres_role_check_fails_closed_on_privileged_role(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_psycopg(
        monkeypatch,
        {
            "app_user": role_script(current_user="postgres", rolsuper=True, rolbypassrls=True),
            "consolidator_user": consolidator_script(),
        },
    )

    with pytest.raises(SystemExit):
        cmd_postgres_role_check(make_args())

    report = json.loads(capsys.readouterr().out)
    codes = {finding["code"] for finding in report["findings"]}
    assert report["ok"] is False
    assert "app_role_safety_failed" in codes


def test_cmd_postgres_role_check_allows_documented_fk_cascade_app_delete(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # roles.sql grants the app role DELETE on exactly the ON DELETE CASCADE targets
    # (justifications, contradictions), which PostgreSQL executes as their owner
    # (mnemosyne_app). The check must accept that documented, narrow exception while
    # the hard-delete boundary stays RLS + the capability layer.
    app = role_script(
        table_rows=[
            ("audit_log", False, False, False),
            ("justifications", True, False, True),
            ("contradictions", True, False, True),
            ("memories", False, False, True),
        ]
    )
    install_fake_psycopg(
        monkeypatch,
        {"app_user": app, "consolidator_user": consolidator_script()},
    )

    cmd_postgres_role_check(make_args())

    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["findings"] == []
    destructive = next(
        c for c in report["checks"] if c["name"] == "app_destructive_writes_denied"
    )
    assert destructive["ok"] is True
    assert destructive["delete_table_count"] == 2
    assert destructive["delete_tables_outside_fk_cascade"] == []
    assert destructive["allowed_fk_cascade_delete_tables"] == [
        "contradictions",
        "justifications",
    ]


def test_cmd_postgres_role_check_fails_on_app_delete_outside_fk_cascade(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # DELETE on any table beyond the documented FK-cascade allowlist must fail closed,
    # and TRUNCATE anywhere is never permitted for the app role.
    app = role_script(
        table_rows=[
            ("audit_log", False, False, False),
            ("justifications", True, False, True),
            ("memories", True, False, True),
        ]
    )
    install_fake_psycopg(
        monkeypatch,
        {"app_user": app, "consolidator_user": consolidator_script()},
    )

    with pytest.raises(SystemExit):
        cmd_postgres_role_check(make_args())

    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert "app_destructive_writes_denied_failed" in {
        finding["code"] for finding in report["findings"]
    }
    destructive = next(
        c for c in report["checks"] if c["name"] == "app_destructive_writes_denied"
    )
    assert destructive["ok"] is False
    assert destructive["delete_tables_outside_fk_cascade"] == ["memories"]


def test_cmd_postgres_role_check_requires_consolidator_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_psycopg(monkeypatch, {"app_user": role_script()})

    with pytest.raises(SystemExit):
        cmd_postgres_role_check(make_args(consolidator_dsn=None))

    report = json.loads(capsys.readouterr().out)
    codes = {finding["code"] for finding in report["findings"]}
    assert "postgres_role_consolidator_dsn_missing" in codes


def test_cmd_postgres_role_check_rejects_local_targets_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_psycopg(
        monkeypatch,
        {"app_user": role_script(), "consolidator_user": consolidator_script()},
    )
    args = make_args(
        app_dsn="postgresql://app_user@localhost:5432/mnemosyne",
        consolidator_dsn="postgresql://consolidator_user@localhost:5432/mnemosyne",
    )

    with pytest.raises(SystemExit):
        cmd_postgres_role_check(args)

    report = json.loads(capsys.readouterr().out)
    codes = {finding["code"] for finding in report["findings"]}
    assert "postgres_role_target_local" in codes

    # The same targets pass with the explicit local escape hatch (dev/compose).
    install_fake_psycopg(
        monkeypatch,
        {"app_user": role_script(), "consolidator_user": consolidator_script()},
    )
    args = make_args(
        app_dsn="postgresql://app_user@localhost:5432/mnemosyne",
        consolidator_dsn="postgresql://consolidator_user@localhost:5432/mnemosyne",
        allow_localhost=True,
    )
    cmd_postgres_role_check(args)
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True


def test_cmd_postgres_role_check_fails_on_sole_write_violation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The consolidator lost DELETE on a domain table: sole-write is not proven.
    weak_consolidator = role_script(
        current_user="consolidator_user",
        table_rows=[
            ("audit_log", False, False, False),
            ("memories", False, False, True),
        ],
    )
    install_fake_psycopg(
        monkeypatch,
        {"app_user": role_script(), "consolidator_user": weak_consolidator},
    )

    with pytest.raises(SystemExit):
        cmd_postgres_role_check(make_args())

    report = json.loads(capsys.readouterr().out)
    codes = {finding["code"] for finding in report["findings"]}
    assert "consolidator_sole_write_failed" in codes


def test_cmd_postgres_role_check_records_probe_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FailingPsycopgModule:
        @staticmethod
        @contextlib.contextmanager
        def connect(dsn: str, *, autocommit: bool = False, connect_timeout: int = 0) -> Any:
            raise OSError("connection refused")
            yield  # pragma: no cover

    monkeypatch.setitem(sys.modules, "psycopg", FailingPsycopgModule())

    with pytest.raises(SystemExit):
        cmd_postgres_role_check(make_args())

    report = json.loads(capsys.readouterr().out)
    codes = {finding["code"] for finding in report["findings"]}
    assert "postgres_role_probe_failed" in codes
    assert "postgres_role_app_probe_missing" in codes
