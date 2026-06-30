"""Postgres production-safety checks shared by durable backends."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def env_flag(name: str, *, default: bool = False) -> bool:
    """Return a strict boolean interpretation for production env flags."""

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def postgres_safe_role_required() -> bool:
    """Whether Postgres connections must refuse privileged runtime roles."""

    return env_flag("MNEMOSYNE_POSTGRES_REQUIRE_SAFE_ROLE", default=False)


@dataclass(frozen=True, slots=True)
class PostgresRoleSafetyReport:
    current_user: str
    rolsuper: bool
    rolbypassrls: bool


def inspect_postgres_role(conn: Any) -> PostgresRoleSafetyReport:
    """Inspect the active Postgres role for RLS-bypassing privileges."""

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT current_user, rolsuper, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
            """
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("Postgres safe-role check failed: current_user is absent from pg_roles.")
    return PostgresRoleSafetyReport(
        current_user=str(row[0]),
        rolsuper=bool(row[1]),
        rolbypassrls=bool(row[2]),
    )


def assert_postgres_safe_role(conn: Any, *, surface: str = "Postgres") -> PostgresRoleSafetyReport:
    """Fail closed when a production Postgres connection can bypass RLS."""

    report = inspect_postgres_role(conn)
    if report.rolsuper or report.rolbypassrls:
        raise RuntimeError(
            f"{surface} production role must be NOSUPERUSER and NOBYPASSRLS "
            f"(current_user={report.current_user!r}, "
            f"rolsuper={report.rolsuper}, rolbypassrls={report.rolbypassrls})."
        )
    return report
