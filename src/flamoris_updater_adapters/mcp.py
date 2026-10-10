from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from starlette.middleware.authentication import AuthenticationMiddleware

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps

from .inputs import TOOLS, Facade
from .managed import MANAGED_TOOLS
from .self_update import runtime_identity


class Verifier:
    def __init__(self, auth):
        self.auth = auth

    async def verify_token(self, token):
        try:
            subject = self.auth.bearer(token)
            return AccessToken(token=token, client_id=subject, subject=subject, scopes=["mcp"])
        except UpdateError:
            return None


def create_mcp(coordinator, auth, origin):
    facade = Facade(coordinator)
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
            for name, (model, description, kind) in (
                MANAGED_TOOLS
                if hasattr(coordinator, "managed_invoke")
                else {name: spec for name, spec in TOOLS.items() if name not in MANAGED_TOOLS}
            ).items()
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            token = get_access_token()
            if token is None:
                raise UpdateError("unauthorized")
            # Tool schemas and runtime validation use exactly the same strict model.
            result = facade.invoke(token.client_id, name, arguments or {})
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
    app = RequireAuthMiddleware(manager.handle_request, required_scopes=["mcp"])
    app = AuthContextMiddleware(app)
    app = AuthenticationMiddleware(app, backend=BearerAuthBackend(Verifier(auth)))
    return app, manager
