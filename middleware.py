import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from access_logging import log_access


logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "font-src 'self' https://cdn.jsdelivr.net"
        )
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.info(f"REQUEST: {request.method} {request.url}")
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        try:
            response = await call_next(request)
        except Exception:
            username = getattr(request.state, "username", "unknown")
            await log_access(
                username,
                request.method,
                request.url.path,
                500,
                "Unhandled server error",
                ip=client_ip,
                user_agent=user_agent,
            )
            raise

        username = getattr(request.state, "username", "unknown")
        await log_access(
            username,
            request.method,
            request.url.path,
            response.status_code,
            "HTTP response completed",
            ip=client_ip,
            user_agent=user_agent,
        )
        logger.info(f"RESPONSE: {request.method} {request.url} - Status: {response.status_code}")
        return response
