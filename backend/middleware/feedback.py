"""Bound the size and frequency of public feedback submissions before parsing JSON."""

import asyncio

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse

MAX_FEEDBACK_BODY = 32 * 1024


class FeedbackBoundaryMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") != "/api/feedback"
            or scope["method"] != "POST"
        ):
            await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        async def reject(status: int, code: str, message: str, headers=None):
            await JSONResponse(
                {"detail": {"code": code, "message": message}}, status_code=status, headers=headers
            )(scope, receive, secure_send)

        limiter = getattr(scope["app"].state, "feedback_limiter", None)
        if limiter is None:
            await reject(
                503, "STORAGE_UNAVAILABLE", "의견 접수를 준비 중입니다. 잠시 후 다시 시도해 주세요."
            )
            return
        client = (scope.get("client") or ("unknown", 0))[0]
        if not limiter.allow(client):
            await reject(
                429,
                "RATE_LIMITED",
                "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                {"Retry-After": "60"},
            )
            return
        content_type = Headers(scope=scope).get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            await reject(415, "INVALID_REQUEST", "JSON 형식으로 요청해 주세요.")
            return

        body = bytearray()
        try:
            async for chunk in Request(scope, receive).stream():
                if len(body) + len(chunk) > MAX_FEEDBACK_BODY:
                    await reject(413, "INVALID_REQUEST", "의견 요청의 크기가 너무 큽니다.")
                    return
                body.extend(chunk)
        except (ClientDisconnect, asyncio.CancelledError):
            return
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, secure_send)
