"""Explicit public path prefixes; never trust forwarded-prefix headers."""

import re

from starlette.responses import JSONResponse, RedirectResponse


def base_path(value):
    if len(value) > 256 or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", value):
        raise ValueError("Use an empty base path or slash-separated letters, digits, '-' and '_'")
    return value


class Prefix:
    def __init__(self, app, prefix):
        self.app, self.prefix = app, base_path(prefix)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.prefix:
            if scope["path"] == self.prefix:
                await RedirectResponse(self.prefix + "/", status_code=308)(scope, receive, send)
                return
            if not scope["path"].startswith(self.prefix + "/"):
                await JSONResponse({"error": "not_found"}, status_code=404)(scope, receive, send)
                return
            # Keep the external path intact. Starlette removes root_path for
            # route matching, including the nested static-files mount.
            scope = {**scope, "root_path": scope.get("root_path", "") + self.prefix}
        await self.app(scope, receive, send)
