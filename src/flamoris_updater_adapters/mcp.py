from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps

from .managed import MANAGED_TOOLS
from .self_update import runtime_identity


def create_mcp(coordinator, origin):
    server = Server("flamoris-updater", version=runtime_identity()["version"])

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name=name,
                description=description,
                inputSchema=model.model_json_schema(),
                annotations=ToolAnnotations(
                    readOnlyHint=kind == "read",
                    destructiveHint=kind == "execute",
                    idempotentHint=kind in {"read", "plan", "execute", "cancel", "verify"},
                    openWorldHint=False,
                ),
            )
            for name, (model, description, kind) in MANAGED_TOOLS.items()
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            result = coordinator.managed_invoke("local", name, arguments or {})
            return CallToolResult(
                content=[TextContent(type="text", text=dumps(result).decode())],
                structuredContent=result,
                isError=False,
            )
        except UpdateError as error:
            result = error.public()
            return CallToolResult(
                content=[TextContent(type="text", text=dumps(result).decode())],
                structuredContent=result,
                isError=True,
            )
        except Exception:
            result = {
                "error": "outcome_unknown",
                "message": "Inspect the durable Job before continuing",
            }
            return CallToolResult(
                content=[TextContent(type="text", text=dumps(result).decode())],
                structuredContent=result,
                isError=True,
            )

    from urllib.parse import urlsplit

    hostname = urlsplit(origin).netloc
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        max_request_body_size=1024 * 1024,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=[hostname], allowed_origins=[origin]
        ),
    )

    class Endpoint:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    return Endpoint(), manager
