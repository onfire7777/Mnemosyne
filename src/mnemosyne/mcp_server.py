"""Minimal stdio JSON-RPC server for the Mnemosyne MCP facade."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import inspect
import json
import os
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import UnionType
from typing import Any, Literal, TextIO, Union, get_args, get_origin, get_type_hints
from urllib.parse import parse_qsl, unquote, urlsplit

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestionPipeline
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC
from mnemosyne.oidc_jwks import load_oidc_authorization_policy, load_oidc_jwks, oidc_jwks_loader
from mnemosyne.parametric import CommandParametricTrainer, ParametricArtifactStore, ParametricTier
from mnemosyne.postgres_runtime_state import PostgresRuntimeState
from mnemosyne.queue import InProcessQueue, PostgresQueue
from mnemosyne.runtime_state import RuntimeState
from mnemosyne.security import (
    OidcJwtVerifier,
    SessionAuthError,
    SessionIdentity,
    SessionTokenVerifier,
    issue_session_from_oidc,
    load_session_secret_command,
    parse_session_keyring,
    parse_session_revoke_list,
)
from mnemosyne.storage import CommandKeyManager, EncryptedLocalObjectStore, JsonKeyManager, LocalObjectStore


PROTOCOL_VERSION = "2024-11-05"
DEFAULT_HTTP_MAX_BODY_BYTES = 1_048_576


class MnemosyneMcpServer:
    """Small JSON-RPC shim around MemoryTools.

    It intentionally keeps the transport simple and deterministic. The exposed
    methods mirror the common MCP handshake shape: initialize, tools/list, and
    tools/call.
    """

    def __init__(
        self,
        store_path: str | os.PathLike[str] | None = None,
        auth_token: str | None = None,
        session_secret: str | None = None,
        session_keyring: str | None = None,
        session_secret_command: str | None = None,
        session_secret_command_timeout: float = 10.0,
        session_key_id: str | None = None,
        session_revoked_key_ids: str | None = None,
        session_revoked_ids: str | None = None,
        require_session: bool | None = None,
        backend: str = "local",
        postgres_dsn: str | None = None,
        parametric_artifact_store: str | os.PathLike[str] | None = None,
        parametric_provider: str | None = None,
        parametric_command: str | None = None,
        parametric_adapter_kind: str | None = None,
        parametric_timeout: float | None = None,
        stateless: bool = False,
        object_store: str | os.PathLike[str] | None = None,
        object_store_encryption: str | None = None,
        object_key_store: str | os.PathLike[str] | None = None,
        object_key_provider: str | None = None,
        object_key_command: str | None = None,
        object_key_timeout: float | None = None,
        allowed_residencies: tuple[str, ...] | None = None,
        runtime_residency: str | None = None,
        allowed_residency_transfers: tuple[str, ...] | None = None,
        require_runtime_residency: bool | None = None,
        queue_backend: str | None = None,
        queue_tenant: str | None = None,
        production_profile: bool | None = None,
    ):
        if backend not in {"local", "postgres"}:
            raise ValueError(f"Unsupported MCP backend: {backend}")
        resolved_queue_backend = (
            queue_backend
            or os.environ.get("MNEMOSYNE_MCP_QUEUE_BACKEND")
            or os.environ.get("MNEMOSYNE_QUEUE_BACKEND")
            or ("postgres" if backend == "postgres" else "local")
        )
        if resolved_queue_backend not in {"local", "postgres"}:
            raise ValueError(f"Unsupported MCP queue backend: {resolved_queue_backend}")
        if stateless and backend == "local" and not store_path:
            raise ValueError("Stateless local MCP mode requires a durable store_path.")
        self.store_path = store_path
        self.backend = backend
        self.postgres_dsn = postgres_dsn
        self.queue_backend = resolved_queue_backend
        self.queue_tenant = (
            queue_tenant
            or os.environ.get("MNEMOSYNE_MCP_QUEUE_TENANT")
            or os.environ.get("MNEMOSYNE_QUEUE_TENANT")
            or "system"
        )
        self.parametric_artifact_store = parametric_artifact_store
        self.parametric_provider = parametric_provider or os.environ.get("MNEMOSYNE_PARAMETRIC_PROVIDER", "local")
        self.parametric_command = parametric_command or os.environ.get("MNEMOSYNE_PARAMETRIC_COMMAND")
        self.parametric_adapter_kind = parametric_adapter_kind or os.environ.get(
            "MNEMOSYNE_PARAMETRIC_ADAPTER_KIND", "command-parametric-adapter"
        )
        self.parametric_timeout = parametric_timeout or float(os.environ.get("MNEMOSYNE_PARAMETRIC_TIMEOUT", "300"))
        self.object_store = object_store or os.environ.get("MNEMOSYNE_OBJECT_STORE") or ".mnemosyne/objects"
        self.object_store_encryption = object_store_encryption or os.environ.get("MNEMOSYNE_OBJECT_STORE_ENCRYPTION", "none")
        self.object_key_store = object_key_store or os.environ.get("MNEMOSYNE_OBJECT_KEY_STORE")
        self.object_key_provider = object_key_provider or _default_object_key_provider()
        self.object_key_command = object_key_command or os.environ.get("MNEMOSYNE_OBJECT_KEY_COMMAND")
        self.object_key_timeout = object_key_timeout or float(os.environ.get("MNEMOSYNE_OBJECT_KEY_TIMEOUT", "30"))
        self.production_profile = (
            bool(production_profile)
            if production_profile is not None
            else _env_flag("MNEMOSYNE_MCP_PRODUCTION_PROFILE", default=False)
        )
        self.allowed_residencies = allowed_residencies or _default_allowed_residencies()
        self.runtime_residency = runtime_residency or os.environ.get("MNEMOSYNE_RUNTIME_RESIDENCY")
        self.allowed_residency_transfers = (
            allowed_residency_transfers
            if allowed_residency_transfers is not None
            else _default_allowed_residency_transfers()
        )
        self.require_runtime_residency = (
            bool(require_runtime_residency)
            if require_runtime_residency is not None
            else _env_flag("MNEMOSYNE_REQUIRE_RUNTIME_RESIDENCY", default=False)
        )
        self.stateless = stateless
        self.auth_token = auth_token if auth_token is not None else os.environ.get("MNEMOSYNE_MCP_TOKEN")
        self.session_secret = (
            session_secret if session_secret is not None else os.environ.get("MNEMOSYNE_MCP_SESSION_SECRET")
        )
        self.session_keyring = (
            session_keyring if session_keyring is not None else os.environ.get("MNEMOSYNE_MCP_SESSION_KEYRING")
        )
        self.session_secret_command = (
            session_secret_command
            if session_secret_command is not None
            else os.environ.get("MNEMOSYNE_MCP_SESSION_SECRET_COMMAND")
        )
        self.session_secret_command_timeout = session_secret_command_timeout
        self.session_key_id = (
            session_key_id if session_key_id is not None else os.environ.get("MNEMOSYNE_MCP_SESSION_KEY_ID")
        )
        self.session_revoked_key_ids = (
            session_revoked_key_ids
            if session_revoked_key_ids is not None
            else os.environ.get("MNEMOSYNE_MCP_SESSION_REVOKED_KEY_IDS")
        )
        self.session_revoked_ids = (
            session_revoked_ids
            if session_revoked_ids is not None
            else os.environ.get("MNEMOSYNE_MCP_SESSION_REVOKED_IDS")
        )
        self.require_session = (
            bool(require_session)
            if require_session is not None
            else _env_flag("MNEMOSYNE_MCP_REQUIRE_SESSION", default=False)
        )
        self._enforce_production_profile()
        self.tool_names = {item["name"] for item in TOOL_SPEC}
        self.tool_specs = [_to_mcp_tool_spec(item) for item in TOOL_SPEC]
        self.tool_schemas_by_name = {item["name"]: item["inputSchema"] for item in self.tool_specs}
        if not self.stateless:
            self.engine, self.queue, self.runtime_state, self.tools = self._build_tools()

    def _build_tools(self, queue_tenant: str | None = None) -> tuple[Any, Any, Any, MemoryTools]:
        if self.backend == "postgres":
            dsn = self.postgres_dsn or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
            if not dsn:
                raise ValueError("Postgres MCP backend requires postgres_dsn or MNEMOSYNE_POSTGRES_DSN.")
            try:
                from mnemosyne.postgres_engine import PostgresEngine
            except ImportError as exc:  # pragma: no cover - defensive for broken installs.
                raise ValueError("Postgres MCP backend requires mnemosyne-memory[postgres].") from exc
            runtime_tenant = queue_tenant or self.queue_tenant
            engine = PostgresEngine(dsn)
            runtime_state = PostgresRuntimeState(dsn, tenant_id=runtime_tenant)
        else:
            engine = LocalMemoryEngine(store_path=self.store_path)
            runtime_state = RuntimeState.from_store_path(self.store_path)
        if self.queue_backend == "postgres":
            dsn = self.postgres_dsn or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
            if not dsn:
                raise ValueError("Postgres MCP queue backend requires postgres_dsn or MNEMOSYNE_POSTGRES_DSN.")
            queue = PostgresQueue(dsn, tenant_id=queue_tenant or self.queue_tenant)
        else:
            queue = runtime_state.load_queue() if runtime_state else InProcessQueue()
        ingestion = IngestionPipeline(
            engine,
            object_store=_load_object_store(
                self.object_store,
                self.object_store_encryption,
                self.object_key_store,
                self.object_key_provider,
                self.object_key_command,
                self.object_key_timeout,
            ),
            queue=queue,
            allowed_residencies=self.allowed_residencies,
            runtime_residency=self.runtime_residency,
            allowed_residency_transfers=self.allowed_residency_transfers,
            require_runtime_residency=self.require_runtime_residency,
        )
        parametric = ParametricTier(
            ParametricArtifactStore(_parametric_store_path(self.store_path, self.parametric_artifact_store)),
            trainer=_load_parametric_trainer(
                self.parametric_provider,
                self.parametric_command,
                self.parametric_adapter_kind,
                self.parametric_timeout,
            ),
        )
        tools = MemoryTools(engine, ingestion=ingestion, runtime_state=runtime_state, parametric=parametric)
        return engine, queue, runtime_state, tools

    def _enforce_production_profile(self) -> None:
        if not self.production_profile:
            return
        if not self.require_session:
            raise ValueError("Production MCP profile requires MNEMOSYNE_MCP_REQUIRE_SESSION=1.")
        if self._session_verifier() is None:
            raise ValueError(
                "Production MCP profile requires signed-session verifier custody "
                "(session secret, keyring, or session-secret command)."
            )
        if self.object_store_encryption != "aesgcm":
            raise ValueError("Production MCP profile requires MNEMOSYNE_OBJECT_STORE_ENCRYPTION=aesgcm.")
        if self.object_key_provider != "command" or not self.object_key_command:
            raise ValueError("Production MCP profile requires command-backed object key custody.")

    @staticmethod
    def _save_queue(runtime_state: RuntimeState | None, queue: Any) -> None:
        if runtime_state and isinstance(queue, InProcessQueue):
            runtime_state.save_queue(queue)


    @staticmethod
    def _queue_tenant_from_arguments(arguments: dict[str, Any]) -> str | None:
        for key in ("tenant_id", "tenant"):
            value = arguments.get(key)
            if isinstance(value, str) and value:
                return value
        return None


    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        if method == "notifications/initialized":
            return None
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": "mnemosyne-memory", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                }
            elif method == "tools/list":
                result = {"tools": self.tool_specs}
            elif method == "tools/call":
                params = request.get("params") or {}
                try:
                    if not isinstance(params, dict):
                        result = _tool_error("Tool params must be a JSON object")
                    elif not self._authorized(params):
                        result = _tool_error("unauthorized: valid MCP auth token required")
                    else:
                        name = str(params.get("name"))
                        arguments = params["arguments"] if "arguments" in params else {}
                        if not isinstance(arguments, dict):
                            result = _tool_error("Tool arguments must be a JSON object")
                        else:
                            prepared_arguments = self.prepare_tool_arguments(name, params, arguments)
                            _validate_tool_arguments(name, prepared_arguments, self.tool_schemas_by_name)
                            result = _tool_result(self.call_tool(name, prepared_arguments))
                except Exception as exc:  # noqa: BLE001 - tool errors are MCP results, not transport failures.
                    result = _tool_error(str(exc))
            else:
                return _error(request_id, -32601, f"Unknown method: {method}")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - JSON-RPC must marshal failures.
            return _error(request_id, -32000, str(exc))

    def _authorized(self, params: dict[str, Any]) -> bool:
        if not self.auth_token:
            return True
        supplied = params.get("auth_token")
        meta = params.get("_meta")
        if supplied is None and isinstance(meta, dict):
            supplied = meta.get("auth_token")
        return isinstance(supplied, str) and hmac.compare_digest(supplied, self.auth_token)

    def prepare_tool_arguments(
        self,
        name: str,
        params: dict[str, Any] | None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Strip transport metadata and bind signed session claims to tool args."""

        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        clean_arguments = dict(arguments)
        argument_meta = clean_arguments.pop("_meta", None)
        clean_arguments.pop("auth_token", None)
        token = clean_arguments.pop("session_token", None)
        params = params or {}
        if token is None:
            token = params.get("session_token")
        params_meta = params.get("_meta")
        if token is None and isinstance(params_meta, dict):
            token = params_meta.get("session_token")
        if token is None and isinstance(argument_meta, dict):
            token = argument_meta.get("session_token")
        if token is None:
            if self.require_session:
                raise PermissionError("session token required")
            return clean_arguments
        if not isinstance(token, str) or not token:
            raise PermissionError("session token must be a non-empty string")
        verifier = self._session_verifier()
        if verifier is None:
            raise PermissionError("session token denied: session secret is not configured")
        try:
            identity = verifier.verify(token)
        except SessionAuthError as exc:
            raise PermissionError(f"session token denied: {exc}") from exc
        return self._bind_session_identity(name, clean_arguments, identity)

    def _session_verifier(self) -> SessionTokenVerifier | None:
        keyring = parse_session_keyring(self.session_keyring)
        revoked_key_ids = parse_session_revoke_list(self.session_revoked_key_ids)
        revoked_session_ids = parse_session_revoke_list(self.session_revoked_ids)
        sources = sum([bool(keyring), bool(self.session_secret), bool(self.session_secret_command)])
        if sources > 1:
            raise SessionAuthError(
                "MCP session auth requires at most one of --session-secret, --session-keyring, or --session-secret-command"
            )
        material: str | dict[str, str] | None = None
        active_key_id = self.session_key_id
        if keyring:
            material = keyring
        elif self.session_secret_command:
            material, command_active_key_id = load_session_secret_command(
                self.session_secret_command,
                timeout_seconds=float(self.session_secret_command_timeout),
            )
            active_key_id = active_key_id or command_active_key_id
        elif self.session_secret:
            material = self.session_secret
        if material is None:
            return None
        if isinstance(material, dict):
            return SessionTokenVerifier(
                material,
                active_key_id=active_key_id,
                revoked_key_ids=revoked_key_ids,
                revoked_session_ids=revoked_session_ids,
            )
        return SessionTokenVerifier(
            material,
            revoked_key_ids=revoked_key_ids,
            revoked_session_ids=revoked_session_ids,
        )

    def _bind_session_identity(
        self,
        name: str,
        arguments: dict[str, Any],
        identity: SessionIdentity,
    ) -> dict[str, Any]:
        parameter_names = self._tool_parameter_names(name)
        for key in ("tenant_id", "tenant"):
            if key in arguments:
                self._bind_string_claim(arguments, key, identity.tenant_id, "tenant")
        for key in ("user_id", "user"):
            if key in arguments:
                self._bind_string_claim(arguments, key, identity.user_id, "user")
        if "tenant_id" in parameter_names:
            self._bind_string_claim(arguments, "tenant_id", identity.tenant_id, "tenant")
        if "tenant" in parameter_names:
            self._bind_string_claim(arguments, "tenant", identity.tenant_id, "tenant")
        if "user_id" in parameter_names:
            self._bind_string_claim(arguments, "user_id", identity.user_id, "user")
        if "user" in parameter_names:
            self._bind_string_claim(arguments, "user", identity.user_id, "user")
        if "role" in parameter_names:
            arguments["role"] = identity.role
        if "source_trust_tier" in parameter_names:
            arguments["source_trust_tier"] = identity.source_trust_tier
        if "trust_tier" in parameter_names:
            arguments["trust_tier"] = identity.source_trust_tier
        if "source_identity" in parameter_names and "source_identity" not in arguments and identity.session_id:
            arguments["source_identity"] = identity.session_id
        return arguments

    @staticmethod
    def _bind_string_claim(arguments: dict[str, Any], key: str, value: str, label: str) -> None:
        current = arguments.get(key)
        if current is None or current == "":
            arguments[key] = value
            return
        if str(current) != value:
            raise PermissionError(f"session {label} mismatch: tool argument does not match authenticated session")

    @staticmethod
    def _tool_parameter_names(name: str) -> set[str]:
        if not hasattr(MemoryTools, name):
            return set()
        signature = inspect.signature(getattr(MemoryTools, name))
        return {key for key in signature.parameters if key != "self"}

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.tool_names:
            raise ValueError(f"Unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        if self.stateless:
            _, queue, runtime_state, tools = self._build_tools(self._queue_tenant_from_arguments(arguments))
            result = getattr(tools, name)(**arguments)
            self._save_queue(runtime_state, queue)
            return result
        result = getattr(self.tools, name)(**arguments)
        self._save_queue(self.runtime_state, self.queue)
        return result

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle(request)
            except json.JSONDecodeError as exc:
                response = _error(None, -32700, f"Invalid JSON: {exc.msg}")
            if response is not None:
                stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                stdout.flush()


def _to_mcp_tool_spec(spec: dict[str, Any]) -> dict[str, Any]:
    method = getattr(MemoryTools, spec["name"], None)
    if method is None:
        properties = {arg: {"type": "string"} for arg in spec["arguments"]}
        required = list(spec["arguments"])
    else:
        signature = inspect.signature(method)
        hints = get_type_hints(method)
        properties = {}
        required = []
        for name, parameter in signature.parameters.items():
            if name == "self":
                continue
            schema = _schema_for_type(hints.get(name, parameter.annotation))
            if parameter.default is not inspect.Parameter.empty:
                schema["default"] = parameter.default
            else:
                required.append(name)
            properties[name] = schema
    return {
        "name": spec["name"],
        "description": spec["description"],
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def _schema_for_type(annotation: Any) -> dict[str, Any]:
    if annotation in {inspect.Parameter.empty, Any}:
        return {}
    if annotation is type(None):
        return {"type": "null"}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in {Union, UnionType}:
        return {"anyOf": [_schema_for_type(arg) for arg in args]}
    if origin is Literal:
        values = list(args)
        schema: dict[str, Any] = {"enum": values}
        if values:
            schema.update(_schema_for_type(type(values[0])))
        return schema
    if origin is list:
        item_type = args[0] if args else Any
        return {"type": "array", "items": _schema_for_type(item_type)}
    if origin is dict:
        return {"type": "object", "additionalProperties": True}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is bytes:
        return {"type": "string", "contentEncoding": "base64"}
    return {}


def _validate_tool_arguments(name: str, arguments: dict[str, Any], schemas_by_name: dict[str, dict[str, Any]]) -> None:
    schema = schemas_by_name.get(name)
    if schema is None:
        raise ValueError(f"Unknown tool: {name}")
    try:
        import jsonschema
    except ImportError:
        _validate_json_schema_subset(arguments, schema)
        return
    try:
        jsonschema.validate(instance=arguments, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Input validation error: {exc.message}") from exc


def _validate_json_schema_subset(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    if "anyOf" in schema:
        errors = []
        for option in schema["anyOf"]:
            try:
                _validate_json_schema_subset(instance, option, path)
                return
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError(f"Input validation error: {path} does not match any allowed schema: {'; '.join(errors)}")
    expected_type = schema.get("type")
    if expected_type and not _json_type_matches(instance, expected_type):
        raise ValueError(f"Input validation error: {path} must be {expected_type}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError(f"Input validation error: {path} must be one of {schema['enum']}")
    if expected_type == "object" or isinstance(instance, dict):
        if not isinstance(instance, dict):
            return
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                raise ValueError(f"Input validation error: {path}.{key} is required")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(instance) - set(properties))
            if extra:
                raise ValueError(f"Input validation error: {path} has unexpected properties: {', '.join(extra)}")
        for key, value in instance.items():
            if key in properties:
                _validate_json_schema_subset(value, properties[key], f"{path}.{key}")
    if expected_type == "array" or isinstance(instance, list):
        if not isinstance(instance, list):
            return
        item_schema = schema.get("items", {})
        for index, value in enumerate(instance):
            _validate_json_schema_subset(value, item_schema, f"{path}[{index}]")


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "null":
        return value is None
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int | float) and not isinstance(value, bool))
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
        "structuredContent": value,
        "isError": False,
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def build_sdk_server(**kwargs: Any) -> Any:
    """Build an official MCP SDK server around the Mnemosyne tool facade."""

    try:
        from mcp import types
        from mcp.server.lowlevel import Server
    except ImportError as exc:  # pragma: no cover - exercised when optional extra is absent.
        raise RuntimeError("Official MCP SDK mode requires `mnemosyne-memory[mcp]`.") from exc

    facade = MnemosyneMcpServer(**kwargs)
    tool_specs = facade.tool_specs
    schemas_by_name = {item["name"]: item["inputSchema"] for item in tool_specs}
    server = Server("mnemosyne-memory", version="0.1.0")

    @server.list_tools()
    async def list_tools() -> list[Any]:
        return [types.Tool(**item) for item in tool_specs]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | Any:
        raw_arguments = dict(arguments or {})
        auth_params: dict[str, Any] = {}
        if "auth_token" in raw_arguments:
            auth_params["auth_token"] = raw_arguments.pop("auth_token")
        if "session_token" in raw_arguments:
            auth_params["session_token"] = raw_arguments.pop("session_token")
        meta = raw_arguments.pop("_meta", None)
        if isinstance(meta, dict):
            auth_params["_meta"] = meta
        if not facade._authorized(auth_params):
            return _sdk_tool_error(types, "unauthorized: valid MCP auth token required")
        schema = schemas_by_name.get(name)
        if schema is None:
            return _sdk_tool_error(types, f"Unknown tool: {name}")
        try:
            raw_arguments = facade.prepare_tool_arguments(name, auth_params, raw_arguments)
        except Exception as exc:  # noqa: BLE001 - SDK tool calls report failures as tool results.
            return _sdk_tool_error(types, str(exc))
        try:
            _validate_tool_arguments(name, raw_arguments, schemas_by_name)
        except ValueError as exc:
            return _sdk_tool_error(types, str(exc))
        try:
            return facade.call_tool(name, raw_arguments)
        except Exception as exc:  # noqa: BLE001 - SDK tool calls report failures as tool results.
            return _sdk_tool_error(types, str(exc))

    return server


def _sdk_tool_error(types_module: Any, message: str) -> Any:
    return types_module.CallToolResult(
        content=[types_module.TextContent(type="text", text=message)],
        isError=True,
    )


async def _serve_sdk_stdio(server: Any) -> None:
    try:
        from mcp.server.stdio import stdio_server
    except ImportError as exc:  # pragma: no cover - exercised when optional extra is absent.
        raise RuntimeError("Official MCP SDK mode requires `mnemosyne-memory[mcp]`.") from exc

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve_sdk_stdio(**kwargs: Any) -> None:
    asyncio.run(_serve_sdk_stdio(build_sdk_server(**kwargs)))


def build_sdk_streamable_http_app(
    *,
    streamable_http_path: str = "/mcp",
    health_path: str = "/healthz",
    stateless: bool = True,
    transport_stateless: bool | None = None,
    **kwargs: Any,
) -> Any:
    """Build an official MCP SDK StreamableHTTP ASGI app."""

    try:
        from mcp.server.fastmcp.server import StreamableHTTPASGIApp
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
    except ImportError as exc:  # pragma: no cover - exercised when optional extra is absent.
        raise RuntimeError("Official MCP SDK streamable HTTP mode requires `mnemosyne-memory[mcp]`.") from exc

    manager_stateless = stateless if transport_stateless is None else transport_stateless
    sdk_kwargs = dict(kwargs)
    sdk_kwargs["stateless"] = stateless
    sdk_server = build_sdk_server(**sdk_kwargs)
    session_manager = StreamableHTTPSessionManager(
        app=sdk_server,
        event_store=None,
        json_response=True,
        stateless=manager_stateless,
        security_settings=None,
    )
    streamable_app = StreamableHTTPASGIApp(session_manager)

    async def health(_request: Any) -> Any:
        return JSONResponse(
            {
                "ok": True,
                "transport": "mcp-sdk-streamable-http",
                "rpc_path": _normalize_http_path(streamable_http_path),
                "stateless": bool(manager_stateless),
            }
        )

    app = Starlette(
        routes=[
            Route(_normalize_http_path(streamable_http_path), endpoint=streamable_app),
            Route(_normalize_http_path(health_path), endpoint=health, methods=["GET"]),
        ],
        lifespan=lambda _app: session_manager.run(),
    )
    app.state.mnemosyne_streamable_http_manager = session_manager
    return app


def serve_sdk_streamable_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    streamable_http_path: str = "/mcp",
    health_path: str = "/healthz",
    stateless: bool = True,
    transport_stateless: bool | None = None,
    **kwargs: Any,
) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised when optional extra is absent.
        raise RuntimeError("Official MCP SDK streamable HTTP mode requires `uvicorn`.") from exc
    app = build_sdk_streamable_http_app(
        streamable_http_path=streamable_http_path,
        health_path=health_path,
        stateless=stateless,
        transport_stateless=transport_stateless,
        **kwargs,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


def build_http_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    rpc_path: str = "/mcp",
    health_path: str = "/healthz",
    session_exchange_path: str = "/session/exchange",
    max_body_bytes: int = DEFAULT_HTTP_MAX_BODY_BYTES,
    idp_jwks: str | None = None,
    idp_jwks_file: str | None = None,
    idp_jwks_url: str | None = None,
    idp_allow_insecure_jwks_url: bool = False,
    idp_authz_policy: str | None = None,
    idp_authz_policy_file: str | None = None,
    idp_issuer: str | None = None,
    idp_audience: str | None = None,
    idp_tenant_claim: str = "tenant_id",
    idp_user_claim: str = "sub",
    idp_role_claim: str = "mnemosyne_role",
    idp_trust_claim: str = "mnemosyne_source_trust_tier",
    idp_session_id_claim: str = "jti",
    idp_algorithms: tuple[str, ...] = ("RS256", "ES256"),
    idp_leeway_seconds: int = 60,
    idp_timeout: float = 10,
    idp_jwks_max_bytes: int = 1024 * 1024,
    idp_jwks_cache_ttl_seconds: int = 300,
    idp_refresh_on_unknown_kid: bool = True,
    session_max_ttl_seconds: int = 3600,
    tls_cert_file: str | None = None,
    tls_key_file: str | None = None,
    tls_client_ca_file: str | None = None,
    tls_require_client_cert: bool = False,
    **kwargs: Any,
) -> ThreadingHTTPServer:
    """Build a hosted HTTP JSON-RPC transport around the MCP facade."""

    facade = MnemosyneMcpServer(**kwargs)
    facade_lock = threading.RLock()
    rpc_path = _normalize_http_path(rpc_path)
    health_path = _normalize_http_path(health_path)
    session_exchange_path = _normalize_http_path(session_exchange_path)
    max_body_bytes = int(max_body_bytes)
    if max_body_bytes <= 0:
        raise ValueError("HTTP MCP max body bytes must be positive")
    idp_verifier: OidcJwtVerifier | None = None
    if idp_issuer or idp_audience or idp_jwks or idp_jwks_file or idp_jwks_url or idp_authz_policy or idp_authz_policy_file:
        if not idp_issuer or not idp_audience:
            raise ValueError("HTTP MCP session exchange requires idp issuer and audience")
        idp_verifier = OidcJwtVerifier(
            load_oidc_jwks(
                jwks=idp_jwks,
                jwks_file=idp_jwks_file,
                jwks_url=idp_jwks_url,
                allow_insecure_url=idp_allow_insecure_jwks_url,
                timeout=idp_timeout,
                max_bytes=idp_jwks_max_bytes,
            ),
            issuer=idp_issuer,
            audience=idp_audience,
            tenant_claim=idp_tenant_claim,
            user_claim=idp_user_claim,
            role_claim=idp_role_claim,
            trust_claim=idp_trust_claim,
            session_id_claim=idp_session_id_claim,
            allowed_algorithms=tuple(item for item in idp_algorithms if item),
            leeway_seconds=idp_leeway_seconds,
            jwks_loader=oidc_jwks_loader(
                jwks=idp_jwks,
                jwks_file=idp_jwks_file,
                jwks_url=idp_jwks_url,
                allow_insecure_url=idp_allow_insecure_jwks_url,
                timeout=idp_timeout,
                max_bytes=idp_jwks_max_bytes,
            ),
            jwks_cache_ttl_seconds=idp_jwks_cache_ttl_seconds,
            refresh_on_unknown_kid=idp_refresh_on_unknown_kid,
            authorization_policy=load_oidc_authorization_policy(
                policy=idp_authz_policy,
                policy_file=idp_authz_policy_file,
            ),
        )

    class Handler(BaseHTTPRequestHandler):
        server_version = "MnemosyneMcpHTTP/0.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name.
            path = urlsplit(self.path).path
            if path != health_path:
                self._send_json(404, {"ok": False, "error": "not found"})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "server": "mnemosyne-memory",
                    "protocolVersion": PROTOCOL_VERSION,
                    "transport": "http-json-rpc",
                    "rpc_path": rpc_path,
                    "session_exchange_path": session_exchange_path,
                    "backend": facade.backend,
                    "stateless": facade.stateless,
                    "production_profile": bool(facade.production_profile),
                    "auth_token_required": bool(facade.auth_token),
                    "session_required": bool(facade.require_session),
                    "session_exchange_configured": idp_verifier is not None,
                    "session_exchange_jwks_cache_ttl_seconds": idp_jwks_cache_ttl_seconds
                    if idp_verifier is not None
                    else None,
                    "session_exchange_refresh_on_unknown_kid": idp_refresh_on_unknown_kid
                    if idp_verifier is not None
                    else None,
                    "session_exchange_authz_policy_configured": idp_verifier.authorization_policy is not None
                    if idp_verifier is not None
                    else False,
                    "tls_enabled": bool(tls_cert_file or tls_key_file),
                    "tls_client_cert_required": bool(tls_require_client_cert),
                },
            )

        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name.
            path = urlsplit(self.path).path
            if path == session_exchange_path:
                self._handle_session_exchange()
                return
            if path != rpc_path:
                self._send_json(404, {"ok": False, "error": "not found"})
                return
            request = self._read_json_request(non_object_message="JSON-RPC request must be an object")
            if isinstance(request, tuple):
                self._send_json(*request)
                return
            with facade_lock:
                response = facade.handle(self._inject_http_auth_metadata(request))
            if response is None:
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self._send_json(200, response)

        def _read_json_request(
            self,
            *,
            non_object_message: str = "JSON request must be an object",
        ) -> dict[str, Any] | tuple[int, dict[str, Any]]:
            length_header = self.headers.get("Content-Length")
            try:
                length = int(length_header or "")
            except ValueError:
                return 411, _error(None, -32600, "Content-Length is required")
            if length < 0:
                return 400, _error(None, -32600, "Content-Length must be non-negative")
            if length > max_body_bytes:
                return 413, _error(None, -32600, "Request body too large")
            raw = self.rfile.read(length)
            try:
                request = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return 400, _error(None, -32700, f"Invalid JSON: {exc}")
            if not isinstance(request, dict):
                return 400, _error(None, -32600, non_object_message)
            return request

        def _handle_session_exchange(self) -> None:
            if idp_verifier is None:
                self._send_json(404, {"ok": False, "error": "session exchange is not configured"})
                return
            request = self._read_json_request()
            if isinstance(request, tuple):
                self._send_json(*request)
                return
            if not self._exchange_authorized(request):
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            idp_token = request.get("idp_token")
            if not isinstance(idp_token, str) or not idp_token:
                self._send_json(400, {"ok": False, "error": "idp_token is required"})
                return
            signer = facade._session_verifier()
            if signer is None:
                self._send_json(503, {"ok": False, "error": "session signing is not configured"})
                return
            try:
                session_token, issued = issue_session_from_oidc(
                    verifier=idp_verifier,
                    idp_token=idp_token,
                    signer=signer,
                    max_ttl_seconds=session_max_ttl_seconds,
                )
            except SessionAuthError:
                self._send_json(401, {"ok": False, "error": "session exchange denied"})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "session_token": session_token,
                    "identity": issued.to_payload(),
                    "expires_at": issued.expires_at,
                },
            )

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _exchange_authorized(self, request: dict[str, Any]) -> bool:
            if not facade.auth_token:
                return True
            supplied = request.get("auth_token")
            meta = request.get("_meta")
            if supplied is None and isinstance(meta, dict):
                supplied = meta.get("auth_token")
            if supplied is None:
                auth_header = self.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    supplied = auth_header.removeprefix("Bearer ").strip()
            return isinstance(supplied, str) and hmac.compare_digest(supplied, facade.auth_token)

        def _inject_http_auth_metadata(self, request: dict[str, Any]) -> dict[str, Any]:
            if request.get("method") != "tools/call":
                return request
            params = request.get("params")
            if not isinstance(params, dict):
                return request
            meta = params.get("_meta")
            auth_meta = dict(meta) if isinstance(meta, dict) else {}
            auth_header = self.headers.get("Authorization", "")
            if auth_header.startswith("Bearer ") and "auth_token" not in auth_meta:
                auth_meta["auth_token"] = auth_header.removeprefix("Bearer ").strip()
            session_header = self.headers.get("X-Mnemosyne-Session-Token")
            if session_header and "session_token" not in auth_meta:
                auth_meta["session_token"] = session_header
            if not auth_meta:
                return request
            cloned_params = dict(params)
            cloned_params["_meta"] = auth_meta
            cloned = dict(request)
            cloned["params"] = cloned_params
            return cloned

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature.
            return

    httpd = ThreadingHTTPServer((host, port), Handler)
    if tls_cert_file or tls_key_file or tls_client_ca_file or tls_require_client_cert:
        if not tls_cert_file or not tls_key_file:
            httpd.server_close()
            raise ValueError("HTTP MCP TLS requires both tls_cert_file and tls_key_file")
        if tls_require_client_cert and not tls_client_ca_file:
            httpd.server_close()
            raise ValueError("HTTP MCP client certificate enforcement requires tls_client_ca_file")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=tls_cert_file, keyfile=tls_key_file)
        if tls_client_ca_file:
            context.load_verify_locations(cafile=tls_client_ca_file)
        context.verify_mode = ssl.CERT_REQUIRED if tls_require_client_cert else ssl.CERT_NONE
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    return httpd


def serve_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    rpc_path: str = "/mcp",
    health_path: str = "/healthz",
    max_body_bytes: int = DEFAULT_HTTP_MAX_BODY_BYTES,
    **kwargs: Any,
) -> None:
    httpd = build_http_server(
        host=host,
        port=port,
        rpc_path=rpc_path,
        health_path=health_path,
        max_body_bytes=max_body_bytes,
        **kwargs,
    )
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def _normalize_http_path(value: str) -> str:
    if not value:
        raise ValueError("HTTP MCP path must be non-empty")
    return value if value.startswith("/") else f"/{value}"


def run_self_test(*, sdk: bool = False, **kwargs: Any) -> dict[str, Any]:
    """Exercise the configured MCP facade without starting stdio service."""

    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, **details: Any) -> None:
        checks.append({"name": name, "ok": ok, **details})

    try:
        server = MnemosyneMcpServer(**kwargs)
    except Exception as exc:  # noqa: BLE001 - self-test reports structured config failures.
        return {"ok": False, "checks": [{"name": "construct", "ok": False, "error": str(exc)}]}

    initialize = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    initialized = initialize.get("result", {}).get("protocolVersion") == PROTOCOL_VERSION
    record("initialize", initialized, protocol=initialize.get("result", {}).get("protocolVersion"))

    tools_list = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = tools_list.get("result", {}).get("tools", [])
    schemas_ok = bool(tools) and all(
        item.get("inputSchema", {}).get("type") == "object"
        and item.get("inputSchema", {}).get("additionalProperties") is False
        for item in tools
    )
    record("tools_list", schemas_ok, tool_count=len(tools))

    auth_params = _self_test_auth_params(server, include_session=False)
    if server.auth_token:
        unauthorized = _self_test_tool_call(server, "residency_policy", {})
        record("auth_token_rejects_missing_token", unauthorized.get("isError") is True)
    else:
        record("auth_token_rejects_missing_token", True, skipped=True, reason="auth token not configured")

    session_token = _self_test_session_token(server)
    if server.require_session:
        missing_session = _self_test_tool_call(server, "residency_policy", {}, auth_params=auth_params)
        record("session_rejects_missing_token", missing_session.get("isError") is True)
        session_config_ok = session_token is not None
        record("session_signing_configured", session_config_ok)
    else:
        record("session_rejects_missing_token", True, skipped=True, reason="signed session not required")
        session_config_ok = True

    authorized_params = _self_test_auth_params(server, include_session=True)
    if server.require_session and session_token is None:
        record("schema_rejects_invalid_arguments", False, error="session token is required but no verifier is configured")
        record("read_only_tool_call", False, error="session token is required but no verifier is configured")
    else:
        invalid_schema = _self_test_tool_call(
            server,
            "residency_policy",
            {"unexpected": True},
            auth_params=authorized_params,
        )
        record("schema_rejects_invalid_arguments", invalid_schema.get("isError") is True)
        read_only = _self_test_tool_call(server, "residency_policy", {}, auth_params=authorized_params)
        record("read_only_tool_call", read_only.get("isError") is False)

    if sdk:
        try:
            build_sdk_server(**kwargs)
            record("sdk_build", True)
        except Exception as exc:  # noqa: BLE001 - optional SDK readiness is a deployment check.
            record("sdk_build", False, error=_redact_self_test_error(str(exc), kwargs, server))

    ok = initialized and schemas_ok and session_config_ok and all(item["ok"] for item in checks)
    return {
        "ok": ok,
        "backend": server.backend,
        "stateless": server.stateless,
        "production_profile": bool(server.production_profile),
        "object_store_encryption": server.object_store_encryption,
        "auth_token_required": bool(server.auth_token),
        "session_required": bool(server.require_session),
        "checks": checks,
    }


def _redact_self_test_error(message: str, kwargs: dict[str, Any], server: MnemosyneMcpServer) -> str:
    sensitive: set[str] = set()
    for key, value in kwargs.items():
        key_l = key.lower()
        if any(
            marker in key_l
            for marker in ("token", "secret", "keyring", "password", "dsn", "credential", "key")
        ) and value:
            value_s = str(value)
            sensitive.add(value_s)
            if "dsn" in key_l:
                sensitive.update(_dsn_sensitive_parts(value_s))
    for value in (
        getattr(server, "auth_token", None),
        getattr(server, "session_secret", None),
        getattr(server, "session_keyring", None),
    ):
        if value:
            sensitive.add(str(value))
    redacted = message
    for value in sorted(sensitive, key=len, reverse=True):
        redacted = redacted.replace(value, "<redacted>")
    return redacted


def _dsn_sensitive_parts(value: str) -> set[str]:
    parts: set[str] = set()
    parsed = urlsplit(value)
    for component in (parsed.username, parsed.password):
        if component:
            parts.add(component)
            parts.add(unquote(component))
    userinfo = parsed.netloc.rsplit("@", 1)[0] if "@" in parsed.netloc else ""
    if ":" in userinfo:
        username, password = userinfo.split(":", 1)
        if username:
            parts.add(username)
            parts.add(unquote(username))
        if password:
            parts.add(password)
            parts.add(unquote(password))
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if "password" in key.lower() and item:
            parts.add(item)
            parts.add(unquote(item))
    for field in parsed.query.split("&"):
        if "=" not in field:
            continue
        key, item = field.split("=", 1)
        if "password" in key.lower() and item:
            parts.add(item)
            parts.add(unquote(item))
    return parts


def _self_test_auth_params(server: MnemosyneMcpServer, *, include_session: bool) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if server.auth_token:
        params["auth_token"] = server.auth_token
    if include_session:
        token = _self_test_session_token(server)
        if token:
            params["session_token"] = token
    return params


def _self_test_session_token(server: MnemosyneMcpServer) -> str | None:
    verifier = server._session_verifier()
    if verifier is None:
        return None
    return verifier.sign(
        SessionIdentity(
            tenant_id="mcp-self-test",
            user_id="mcp-self-test",
            role="operator",
            source_trust_tier=0,
            session_id="mcp-self-test",
        )
    )


def _self_test_tool_call(
    server: MnemosyneMcpServer,
    name: str,
    arguments: dict[str, Any],
    *,
    auth_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = {"name": name, "arguments": dict(arguments)}
    if auth_params:
        params.update(auth_params)
    response = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": params})
    return response.get("result", {})


def default_store() -> Path:
    return Path(os.environ.get("MNEME_STORE", ".mnemosyne/mcp-store.json"))


def default_backend() -> str:
    return os.environ.get("MNEME_BACKEND", "local")


def default_postgres_dsn() -> str | None:
    return os.environ.get("MNEMOSYNE_POSTGRES_DSN")


def _parametric_store_path(
    store_path: str | os.PathLike[str] | None,
    configured_path: str | os.PathLike[str] | None,
) -> Path:
    env_path = os.environ.get("MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE")
    if configured_path:
        return Path(configured_path).expanduser()
    if env_path:
        return Path(env_path).expanduser()
    if store_path:
        path = Path(store_path).expanduser()
        return path.with_suffix(path.suffix + ".parametric")
    return Path(".mnemosyne/mcp-parametric")


def _load_parametric_trainer(
    provider: str,
    command: str | None,
    adapter_kind: str,
    timeout: float,
) -> CommandParametricTrainer | None:
    if provider == "local":
        return None
    if provider == "command":
        if not command:
            raise ValueError("parametric provider command requires parametric_command.")
        return CommandParametricTrainer(command, adapter_kind=adapter_kind, timeout_seconds=timeout)
    raise ValueError(f"Unsupported parametric provider: {provider}")


def _default_allowed_residencies() -> tuple[str, ...]:
    raw = os.environ.get("MNEMOSYNE_ALLOWED_RESIDENCIES", "local")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _default_allowed_residency_transfers() -> tuple[str, ...]:
    raw = os.environ.get("MNEMOSYNE_ALLOWED_RESIDENCY_TRANSFERS", "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_object_key_provider() -> str:
    return os.environ.get("MNEMOSYNE_OBJECT_KEY_PROVIDER") or (
        "command" if os.environ.get("MNEMOSYNE_OBJECT_KEY_COMMAND") else "json"
    )


def _load_object_store(
    root: str | os.PathLike[str],
    encryption: str,
    key_store: str | os.PathLike[str] | None,
    key_provider: str,
    key_command: str | None,
    key_timeout: float,
) -> LocalObjectStore:
    if encryption == "aesgcm":
        if key_provider == "command":
            if not key_command:
                raise ValueError("object key provider command requires object_key_command.")
            return EncryptedLocalObjectStore(
                Path(root),
                CommandKeyManager(key_command, timeout_seconds=key_timeout),
            )
        if key_provider != "json":
            raise ValueError(f"Unsupported object key provider: {key_provider}")
        keys = Path(key_store).expanduser() if key_store else Path(root).expanduser() / ".keys.json"
        return EncryptedLocalObjectStore(Path(root), JsonKeyManager(keys))
    if encryption != "none":
        raise ValueError(f"Unsupported object-store encryption: {encryption}")
    return LocalObjectStore(Path(root))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mneme-mcp", description="Run the Mnemosyne stdio MCP server")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
    parser.add_argument("--backend", choices=["local", "postgres"], default=default_backend(), help="Storage backend for MCP tools")
    parser.add_argument("--postgres-dsn", default=default_postgres_dsn(), help="Postgres DSN for --backend postgres")
    parser.add_argument("--object-store", default=os.environ.get("MNEMOSYNE_OBJECT_STORE", ".mnemosyne/objects"))
    parser.add_argument(
        "--object-store-encryption",
        choices=["none", "aesgcm"],
        default=os.environ.get("MNEMOSYNE_OBJECT_STORE_ENCRYPTION", "none"),
    )
    parser.add_argument("--object-key-store", default=os.environ.get("MNEMOSYNE_OBJECT_KEY_STORE"))
    parser.add_argument(
        "--object-key-provider",
        choices=["json", "command"],
        default=_default_object_key_provider(),
        help="Envelope-key manager for encrypted MCP object storage",
    )
    parser.add_argument(
        "--object-key-command",
        default=os.environ.get("MNEMOSYNE_OBJECT_KEY_COMMAND"),
        help="Command key provider invoked as '<command> <action>' with JSON stdin",
    )
    parser.add_argument(
        "--object-key-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_OBJECT_KEY_TIMEOUT", "30")),
        help="Timeout in seconds for --object-key-provider command",
    )
    parser.add_argument(
        "--allowed-residency",
        action="append",
        default=list(_default_allowed_residencies()),
        help="Allowed data residency label for MCP ingestion; repeat or use MNEMOSYNE_ALLOWED_RESIDENCIES",
    )
    parser.add_argument(
        "--runtime-residency",
        default=os.environ.get("MNEMOSYNE_RUNTIME_RESIDENCY"),
        help="Runtime processing residency for MCP ingestion; cross-region ingestion requires an allowed transfer",
    )
    parser.add_argument(
        "--allowed-residency-transfer",
        action="append",
        default=list(_default_allowed_residency_transfers()),
        help="Allowed MCP cross-region transfer in source->target form; repeat or use MNEMOSYNE_ALLOWED_RESIDENCY_TRANSFERS",
    )
    parser.add_argument(
        "--require-runtime-residency",
        action="store_true",
        default=_env_flag("MNEMOSYNE_REQUIRE_RUNTIME_RESIDENCY", default=False),
        help="Fail MCP ingestion unless a runtime processing residency is configured or supplied in metadata",
    )
    parser.add_argument("--parametric-artifact-store", default=os.environ.get("MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE"))
    parser.add_argument(
        "--parametric-provider",
        choices=["local", "command"],
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_PROVIDER", "local"),
        help="Parametric-tier provider for LoRA/test-time-training adapter artifacts",
    )
    parser.add_argument(
        "--parametric-command",
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_COMMAND"),
        help="Command provider invoked as '<command> <action>' with JSON stdin",
    )
    parser.add_argument(
        "--parametric-adapter-kind",
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_ADAPTER_KIND", "command-parametric-adapter"),
        help="Adapter kind label for --parametric-provider command",
    )
    parser.add_argument(
        "--parametric-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_PARAMETRIC_TIMEOUT", "300")),
        help="Timeout in seconds for --parametric-provider command",
    )
    parser.add_argument(
        "--queue-backend",
        choices=["local", "postgres"],
        default=os.environ.get("MNEMOSYNE_MCP_QUEUE_BACKEND") or os.environ.get("MNEMOSYNE_QUEUE_BACKEND"),
        help="Runtime job queue backend for MCP ingestion",
    )
    parser.add_argument(
        "--queue-tenant",
        default=os.environ.get("MNEMOSYNE_MCP_QUEUE_TENANT") or os.environ.get("MNEMOSYNE_QUEUE_TENANT"),
        help="Fallback tenant scope for MCP Postgres queue jobs",
    )
    parser.add_argument("--stateless", action="store_true", help="Rebuild engine and tool state for each JSON-RPC tool call")
    parser.add_argument("--sdk", action="store_true", help="Use the official MCP Python SDK stdio transport")
    parser.add_argument(
        "--sdk-streamable-http",
        action="store_true",
        default=_env_flag("MNEMOSYNE_MCP_SDK_STREAMABLE_HTTP", default=False),
        help="Serve the official MCP SDK StreamableHTTP transport instead of stdio",
    )
    parser.add_argument(
        "--sdk-streamable-http-path",
        default=os.environ.get("MNEMOSYNE_MCP_SDK_STREAMABLE_HTTP_PATH", "/mcp"),
        help="Official MCP SDK StreamableHTTP endpoint path",
    )
    parser.add_argument(
        "--sdk-streamable-health-path",
        default=os.environ.get("MNEMOSYNE_MCP_SDK_STREAMABLE_HEALTH_PATH", "/healthz"),
        help="Liveness endpoint path for --sdk-streamable-http",
    )
    parser.add_argument(
        "--sdk-streamable-stateful",
        action="store_true",
        default=_env_flag("MNEMOSYNE_MCP_SDK_STREAMABLE_STATEFUL", default=False),
        help="Use stateful StreamableHTTP sessions instead of stateless per-request SDK transports",
    )
    parser.add_argument("--self-test", action="store_true", help="Run MCP deployment validation checks and exit")
    parser.add_argument("--http", action="store_true", help="Serve a hosted HTTP JSON-RPC MCP endpoint instead of stdio")
    parser.add_argument("--http-host", default=os.environ.get("MNEMOSYNE_MCP_HTTP_HOST", "127.0.0.1"))
    parser.add_argument("--http-port", type=int, default=int(os.environ.get("MNEMOSYNE_MCP_HTTP_PORT", "8765")))
    parser.add_argument("--http-rpc-path", default=os.environ.get("MNEMOSYNE_MCP_HTTP_RPC_PATH", "/mcp"))
    parser.add_argument("--http-health-path", default=os.environ.get("MNEMOSYNE_MCP_HTTP_HEALTH_PATH", "/healthz"))
    parser.add_argument("--http-session-exchange-path", default=os.environ.get("MNEMOSYNE_MCP_HTTP_SESSION_EXCHANGE_PATH", "/session/exchange"))
    parser.add_argument(
        "--http-max-body-bytes",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_MCP_HTTP_MAX_BODY_BYTES", str(DEFAULT_HTTP_MAX_BODY_BYTES))),
        help="Maximum HTTP MCP JSON-RPC request body size",
    )
    parser.add_argument(
        "--tls-cert-file",
        default=os.environ.get("MNEMOSYNE_MCP_TLS_CERT_FILE"),
        help="PEM server certificate for HTTPS hosted MCP transport",
    )
    parser.add_argument(
        "--tls-key-file",
        default=os.environ.get("MNEMOSYNE_MCP_TLS_KEY_FILE"),
        help="PEM private key for HTTPS hosted MCP transport",
    )
    parser.add_argument(
        "--tls-client-ca-file",
        default=os.environ.get("MNEMOSYNE_MCP_TLS_CLIENT_CA_FILE"),
        help="PEM CA bundle used to verify hosted MCP client certificates",
    )
    parser.add_argument(
        "--tls-require-client-cert",
        action="store_true",
        default=_env_flag("MNEMOSYNE_MCP_TLS_REQUIRE_CLIENT_CERT", default=False),
        help="Require a client certificate signed by --tls-client-ca-file",
    )
    parser.add_argument("--idp-jwks", default=os.environ.get("MNEMOSYNE_MCP_IDP_JWKS"))
    parser.add_argument("--idp-jwks-file", default=os.environ.get("MNEMOSYNE_MCP_IDP_JWKS_FILE"))
    parser.add_argument("--idp-jwks-url", default=os.environ.get("MNEMOSYNE_MCP_IDP_JWKS_URL"))
    parser.add_argument("--idp-allow-insecure-jwks-url", action="store_true", default=_env_flag("MNEMOSYNE_MCP_IDP_ALLOW_INSECURE_JWKS_URL", default=False))
    parser.add_argument("--idp-authz-policy", default=os.environ.get("MNEMOSYNE_MCP_IDP_AUTHZ_POLICY"))
    parser.add_argument("--idp-authz-policy-file", default=os.environ.get("MNEMOSYNE_MCP_IDP_AUTHZ_POLICY_FILE"))
    parser.add_argument("--idp-issuer", default=os.environ.get("MNEMOSYNE_MCP_IDP_ISSUER"))
    parser.add_argument("--idp-audience", default=os.environ.get("MNEMOSYNE_MCP_IDP_AUDIENCE"))
    parser.add_argument("--idp-tenant-claim", default=os.environ.get("MNEMOSYNE_MCP_IDP_TENANT_CLAIM", "tenant_id"))
    parser.add_argument("--idp-user-claim", default=os.environ.get("MNEMOSYNE_MCP_IDP_USER_CLAIM", "sub"))
    parser.add_argument("--idp-role-claim", default=os.environ.get("MNEMOSYNE_MCP_IDP_ROLE_CLAIM", "mnemosyne_role"))
    parser.add_argument("--idp-trust-claim", default=os.environ.get("MNEMOSYNE_MCP_IDP_TRUST_CLAIM", "mnemosyne_source_trust_tier"))
    parser.add_argument("--idp-session-id-claim", default=os.environ.get("MNEMOSYNE_MCP_IDP_SESSION_ID_CLAIM", "jti"))
    parser.add_argument("--idp-algorithm", action="append", default=os.environ.get("MNEMOSYNE_MCP_IDP_ALGORITHMS", "RS256,ES256").split(","))
    parser.add_argument("--idp-leeway-seconds", type=int, default=int(os.environ.get("MNEMOSYNE_MCP_IDP_LEEWAY_SECONDS", "60")))
    parser.add_argument("--idp-timeout", type=float, default=float(os.environ.get("MNEMOSYNE_MCP_IDP_TIMEOUT", "10")))
    parser.add_argument("--idp-jwks-max-bytes", type=int, default=int(os.environ.get("MNEMOSYNE_MCP_IDP_JWKS_MAX_BYTES", str(1024 * 1024))))
    parser.add_argument("--idp-jwks-cache-ttl-seconds", type=int, default=int(os.environ.get("MNEMOSYNE_MCP_IDP_JWKS_CACHE_TTL_SECONDS", "300")))
    parser.add_argument(
        "--idp-disable-refresh-on-unknown-kid",
        action="store_true",
        default=_env_flag("MNEMOSYNE_MCP_IDP_DISABLE_REFRESH_ON_UNKNOWN_KID", default=False),
    )
    parser.add_argument("--session-max-ttl-seconds", type=int, default=int(os.environ.get("MNEMOSYNE_MCP_SESSION_MAX_TTL_SECONDS", "3600")))
    parser.add_argument("--auth-token", default=os.environ.get("MNEMOSYNE_MCP_TOKEN"), help="Require this token for tools/call")
    parser.add_argument(
        "--session-secret",
        default=os.environ.get("MNEMOSYNE_MCP_SESSION_SECRET"),
        help="HMAC secret for signed MCP session_token claims",
    )
    parser.add_argument(
        "--session-keyring",
        default=os.environ.get("MNEMOSYNE_MCP_SESSION_KEYRING"),
        help="JSON object or comma-separated kid=secret HMAC keyring for signed MCP session_token claims",
    )
    parser.add_argument(
        "--session-secret-command",
        default=os.environ.get("MNEMOSYNE_MCP_SESSION_SECRET_COMMAND"),
        help="Shell-free command provider that returns MCP session secret JSON for deployment secret custody",
    )
    parser.add_argument(
        "--session-secret-command-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_MCP_SESSION_SECRET_COMMAND_TIMEOUT", "10")),
        help="Timeout in seconds for --session-secret-command",
    )
    parser.add_argument(
        "--session-key-id",
        default=os.environ.get("MNEMOSYNE_MCP_SESSION_KEY_ID"),
        help="Active key id used when issuing keyring-backed MCP session tokens",
    )
    parser.add_argument(
        "--session-revoked-key-ids",
        default=os.environ.get("MNEMOSYNE_MCP_SESSION_REVOKED_KEY_IDS"),
        help="Comma-separated MCP session token key ids to reject",
    )
    parser.add_argument(
        "--session-revoked-ids",
        default=os.environ.get("MNEMOSYNE_MCP_SESSION_REVOKED_IDS"),
        help="Comma-separated MCP session ids to reject",
    )
    parser.add_argument(
        "--require-session",
        action="store_true",
        default=_env_flag("MNEMOSYNE_MCP_REQUIRE_SESSION", default=False),
        help="Require a valid signed session_token on tools/call",
    )
    parser.add_argument(
        "--production-profile",
        action="store_true",
        default=_env_flag("MNEMOSYNE_MCP_PRODUCTION_PROFILE", default=False),
        help="Fail closed unless MCP production session and object-key custody controls are active",
    )
    args = parser.parse_args(argv)
    config = {
        "store_path": args.store,
        "auth_token": args.auth_token,
        "session_secret": args.session_secret,
        "session_keyring": args.session_keyring,
        "session_secret_command": args.session_secret_command,
        "session_secret_command_timeout": args.session_secret_command_timeout,
        "session_key_id": args.session_key_id,
        "session_revoked_key_ids": args.session_revoked_key_ids,
        "session_revoked_ids": args.session_revoked_ids,
        "require_session": args.require_session,
        "backend": args.backend,
        "postgres_dsn": args.postgres_dsn,
        "object_store": args.object_store,
        "object_store_encryption": args.object_store_encryption,
        "object_key_store": args.object_key_store,
        "object_key_provider": args.object_key_provider,
        "object_key_command": args.object_key_command,
        "object_key_timeout": args.object_key_timeout,
        "allowed_residencies": tuple(args.allowed_residency),
        "runtime_residency": args.runtime_residency,
        "allowed_residency_transfers": tuple(args.allowed_residency_transfer),
        "require_runtime_residency": args.require_runtime_residency,
        "parametric_artifact_store": args.parametric_artifact_store,
        "parametric_provider": args.parametric_provider,
        "parametric_command": args.parametric_command,
        "parametric_adapter_kind": args.parametric_adapter_kind,
        "parametric_timeout": args.parametric_timeout,
        "queue_backend": args.queue_backend,
        "queue_tenant": args.queue_tenant,
        "stateless": args.stateless,
        "production_profile": args.production_profile,
    }
    if args.self_test:
        report = run_self_test(sdk=args.sdk, **config)
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit(0 if report["ok"] else 1)
    if sum([bool(args.http), bool(args.sdk), bool(args.sdk_streamable_http)]) > 1:
        parser.error("--http, --sdk, and --sdk-streamable-http cannot be combined for serving")
    if args.sdk_streamable_http:
        serve_sdk_streamable_http(
            host=args.http_host,
            port=args.http_port,
            streamable_http_path=args.sdk_streamable_http_path,
            health_path=args.sdk_streamable_health_path,
            transport_stateless=not args.sdk_streamable_stateful,
            **config,
        )
        return
    if args.http:
        serve_http(
            host=args.http_host,
            port=args.http_port,
            rpc_path=args.http_rpc_path,
            health_path=args.http_health_path,
            session_exchange_path=args.http_session_exchange_path,
            max_body_bytes=args.http_max_body_bytes,
            idp_jwks=args.idp_jwks,
            idp_jwks_file=args.idp_jwks_file,
            idp_jwks_url=args.idp_jwks_url,
            idp_allow_insecure_jwks_url=args.idp_allow_insecure_jwks_url,
            idp_authz_policy=args.idp_authz_policy,
            idp_authz_policy_file=args.idp_authz_policy_file,
            idp_issuer=args.idp_issuer,
            idp_audience=args.idp_audience,
            idp_tenant_claim=args.idp_tenant_claim,
            idp_user_claim=args.idp_user_claim,
            idp_role_claim=args.idp_role_claim,
            idp_trust_claim=args.idp_trust_claim,
            idp_session_id_claim=args.idp_session_id_claim,
            idp_algorithms=tuple(args.idp_algorithm),
            idp_leeway_seconds=args.idp_leeway_seconds,
            idp_timeout=args.idp_timeout,
            idp_jwks_max_bytes=args.idp_jwks_max_bytes,
            idp_jwks_cache_ttl_seconds=args.idp_jwks_cache_ttl_seconds,
            idp_refresh_on_unknown_kid=not args.idp_disable_refresh_on_unknown_kid,
            session_max_ttl_seconds=args.session_max_ttl_seconds,
            tls_cert_file=args.tls_cert_file,
            tls_key_file=args.tls_key_file,
            tls_client_ca_file=args.tls_client_ca_file,
            tls_require_client_cert=args.tls_require_client_cert,
            **config,
        )
        return
    if args.sdk:
        serve_sdk_stdio(**config)
    else:
        MnemosyneMcpServer(**config).serve()


if __name__ == "__main__":
    main()
