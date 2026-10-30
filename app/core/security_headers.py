"""ASGI middleware that adds basic security headers to every HTTP response.

The web UI ("/" and "/static/...") also gets a strict Content-Security-Policy: it has no
inline script or style. /docs and /redoc load Swagger UI and ReDoc from a CDN with inline
script, and /api/* returns JSON, so the CSP is not applied to them.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
])


def is_web_ui_path(path: str) -> bool:
    """True for the pages and files of the web UI, which get the CSP."""
    return path == "/" or path.startswith("/static/")


class SecurityHeadersMiddleware:
    """Sets SECURITY_HEADERS on every response (and the CSP on web UI paths),
    replacing any value the app set."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        add_csp = is_web_ui_path(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if add_csp:
                    headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
            await send(message)

        await self.app(scope, receive, send_with_headers)
