"""Return request-local diagnostics to the caller, without a shared log endpoint."""
import base64
from contextvars import ContextVar
import json
import logging

from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


_request_log: ContextVar[list[str] | None] = ContextVar("request_diagnostic", default=None)


class RequestLogHandler(logging.Handler):
    def emit(self, record):
        lines = _request_log.get()
        if lines is not None and len(lines) < 20:
            # No traceback locals, credentials, request bodies or global log files.
            lines.append(self.format(record)[:2000])


async def diagnostic_http_exception(request, exc: HTTPException):
    if exc.__cause__ is not None:
        logging.getLogger(__name__).warning(
            "HTTP %s: %s: %s", exc.status_code,
            type(exc.__cause__).__name__, exc.__cause__,
        )
    return await http_exception_handler(request, exc)


class RequestDiagnosticsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        lines: list[str] = []
        token = _request_log.set(lines)
        started = False

        async def diagnostic_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                if lines:
                    detail = "\n".join(lines)
                    # Keep response headers below common proxy limits; mark truncation.
                    if len(detail) > 2000:
                        detail = detail[:2000] + "\n[Serverdiagnose gekürzt]"
                    payload = json.dumps(detail, ensure_ascii=True).encode("ascii")
                    while len(payload) > 2400:
                        detail = detail[:len(detail) // 2] + "\n[Serverdiagnose gekürzt]"
                        payload = json.dumps(detail, ensure_ascii=True).encode("ascii")
                    encoded = base64.b64encode(payload)
                    message["headers"] = list(message.get("headers", [])) + [
                        (b"x-mediaforge-diagnostic", encoded),
                        (b"cache-control", b"no-store"),
                    ]
            await send(message)

        try:
            await self.app(scope, receive, diagnostic_send)
        except Exception as exc:
            if started:
                raise
            logging.getLogger(__name__).error("%s: %s", type(exc).__name__, exc)
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)
            await response(scope, receive, diagnostic_send)
        finally:
            _request_log.reset(token)


def install_diagnostics(app):
    handler = RequestLogHandler(level=logging.WARNING)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    if not any(isinstance(existing, RequestLogHandler) for existing in logging.getLogger().handlers):
        logging.getLogger().addHandler(handler)
    app.add_exception_handler(HTTPException, diagnostic_http_exception)
    app.add_middleware(RequestDiagnosticsMiddleware)
