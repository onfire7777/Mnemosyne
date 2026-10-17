"""Calling an MCP SDK 2.x server's handlers in process, the way the 1.x ``request_handlers`` map was."""

from typing import Any


def sdk_handler(server: Any, request_type: Any) -> Any:
    """The handler for one request type; called with a request, it gets that request's params."""
    entry = server.get_request_handler(request_type.model_fields["method"].default)

    async def handle(request: Any) -> Any:
        params = getattr(request, "params", None)
        return await entry.handler(None, params if params is not None else entry.params_type())

    return handle
