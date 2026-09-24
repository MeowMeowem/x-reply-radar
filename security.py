"""Keep the local web app local.

- Host header must be localhost (blocks DNS-rebinding pages from reading the API).
- State-changing requests from a browser must come from this same origin (blocks CSRF:
  any website could otherwise POST to 127.0.0.1 and spend your AI credits or send posts).
  Clients that send no Origin (curl, a local integration) are allowed, because a web
  page cannot make a cross-site request without one.
"""
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

import config

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host(value: str) -> str:
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value.split("]")[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def allowed_hosts() -> set:
    extra = {h.strip().lower() for h in (config.env().get("ALLOWED_HOSTS") or "").split(",") if h.strip()}
    return LOCAL_HOSTS | extra


class LocalOnly(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        hosts = allowed_hosts()
        if _host(request.headers.get("host", "")) not in hosts:
            return JSONResponse({"error": "host not allowed"}, status_code=403)
        if request.method not in SAFE_METHODS:
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"error": "cross-site request blocked"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != "null":
                parsed = urlparse(origin)
                if _host(parsed.netloc) not in hosts or parsed.netloc != request.headers.get("host"):
                    return JSONResponse({"error": "cross-origin request blocked"}, status_code=403)
            elif origin == "null":
                return JSONResponse({"error": "opaque origin blocked"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
