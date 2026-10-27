"""Bound public event ingestion and observe completed business responses."""

import asyncio
import logging
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response

from backend.schemas.usage import UsageEventType
from backend.services.usage import VISITOR_SECONDS, browser_id, download_event

logger = logging.getLogger(__name__)
MAX_EVENT_BODY = 4096


def _origin(value: str) -> tuple[str, str | None, int | None] | None:
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        if url.path not in {"", "/"} or url.query or url.fragment:
            return None
        return url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80)
    except ValueError:
        return None


class UsageMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def event_receive(self, scope, receive, send):
        """Reject unsafe event requests before JSON parsing; replay a bounded body."""

        async def reject(status, code, message, headers=None):
            await JSONResponse(
                {"detail": {"code": code, "message": message}},
                status_code=status,
                headers={"Cache-Control": "no-store", **(headers or {})},
            )(scope, receive, send)

        headers = Headers(scope=scope)
        request = Request(scope, receive)
        origins = headers.getlist("origin")
        if (
            len(origins) > 1
            or any(_origin(value) != _origin(str(request.base_url)) for value in origins)
            or headers.get("sec-fetch-site") in {"cross-site", "same-site"}
        ):
            await reject(403, "FORBIDDEN", "허용되지 않은 출처의 통계 요청입니다.")
            return None
        limiter = getattr(scope["app"].state, "usage_limiter", None)
        if getattr(scope["app"].state, "usage_service", None) is None or limiter is None:
            await reject(503, "STORAGE_UNAVAILABLE", "통계 저장소를 사용할 수 없습니다.")
            return None
        if not limiter.allow((scope.get("client") or ("unknown", 0))[0]):
            await reject(429, "RATE_LIMITED", "요청이 너무 많습니다.", {"Retry-After": "60"})
            return None
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            await reject(415, "INVALID_REQUEST", "JSON 형식으로 요청해 주세요.")
            return None
        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_EVENT_BODY:
                    await reject(413, "INVALID_REQUEST", "통계 요청의 크기가 너무 큽니다.")
                    return None
                body.extend(chunk)
        except ClientDisconnect:
            return None
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return replay_receive

    async def record_response(self, scope, service, visitor_id, status, completed):
        path, method = scope["path"], scope["method"]
        event_type = None
        if path == "/api/calculate" and method == "POST":
            event_type = (
                UsageEventType.CALCULATION_SUCCESS
                if status == 200 and completed
                else UsageEventType.CALCULATION_FAILURE
            )
        elif path.startswith("/api/download/") and method == "GET" and status == 200 and completed:
            event_type = download_event(path.removeprefix("/api/download/"))
        elif path == "/api/feedback" and method == "POST" and 200 <= status < 300 and completed:
            event_type = scope["state"].get("usage_event")
        if event_type is not None:
            try:
                await asyncio.to_thread(service.record, event_type, visitor_id)
            except Exception:
                # Never include request data, cookies, or database exception parameters.
                logger.warning("Usage event could not be stored")

    async def __call__(self, scope, receive, send) -> None:
        path, method = scope.get("path", ""), scope.get("method")
        tracked = (
            method == "POST" and path in {"/api/events", "/api/calculate", "/api/feedback"}
        ) or (method == "GET" and (path in {"/", "/index"} or path.startswith("/api/download/")))
        if scope["type"] != "http" or not tracked:
            await self.app(scope, receive, send)
            return
        service = getattr(scope["app"].state, "usage_service", None)
        if path == "/api/events":
            receive = await self.event_receive(scope, receive, send)
            if receive is None:
                return
        elif service is None:
            await self.app(scope, receive, send)
            return

        cookie_name = "__Host-gifttax-visitor" if scope["scheme"] == "https" else "gifttax-visitor"
        visitor_id, fresh = browser_id(Request(scope).cookies.get(cookie_name))
        scope.setdefault("state", {})["usage_visitor_id"] = visitor_id
        status, completed = 500, False

        async def observe_send(message):
            nonlocal status, completed
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                if fresh:
                    cookie = Response()
                    cookie.set_cookie(
                        cookie_name,
                        visitor_id,
                        max_age=VISITOR_SECONDS,
                        httponly=True,
                        secure=scope["scheme"] == "https",
                        samesite="lax",
                        path="/",
                    )
                    headers.append("Set-Cookie", cookie.headers["set-cookie"])
            await send(message)
            if (
                message["type"] == "http.response.body" and not message.get("more_body", False)
            ) or (message["type"] == "http.response.pathsend"):
                completed = True

        try:
            await self.app(scope, receive, observe_send)
        finally:
            await self.record_response(scope, service, visitor_id, status, completed)
