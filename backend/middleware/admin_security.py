"""HTTP boundary for private admin routes; public API CORS remains independent."""

import asyncio
from collections import OrderedDict, deque
from threading import Lock
from time import monotonic

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

from backend.settings import AdminSettings

MAX_ADMIN_BODY = 64 * 1024
ADMIN_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}


class AdminRateLimiter:
    def __init__(self, per_client: int = 30, total: int = 120) -> None:
        self.per_client, self.total = per_client, total
        self.clients: OrderedDict[str, deque] = OrderedDict()
        self.requests: deque = deque()
        self.lock = Lock()

    def allow(self, client: str, *, now: float | None = None) -> bool:
        now = monotonic() if now is None else now
        with self.lock:
            while self.requests and self.requests[0] <= now - 60:
                self.requests.popleft()
            history = self.clients.setdefault(client, deque())
            self.clients.move_to_end(client)
            while history and history[0] <= now - 60:
                history.popleft()
            if len(self.clients) > 2048:
                self.clients.popitem(last=False)
            if len(history) >= self.per_client or len(self.requests) >= self.total:
                return False
            history.append(now)
            self.requests.append(now)
            return True


class AdminBoundaryMiddleware:
    def __init__(self, app) -> None:
        self.app = app
        self.public = CORSMiddleware(
            app,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    async def __call__(self, scope, receive, send) -> None:
        path = scope.get("path", "")
        is_admin_api = path.startswith("/api/admin")
        private = is_admin_api or path in {"/admin", "/admin/", "/admin.js", "/admin.css"}
        if scope["type"] != "http" or not private:
            await self.public(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in ADMIN_HEADERS.items():
                    headers[key] = value
            await send(message)

        async def reject(status: int, code: str, message: str, headers=None):
            await JSONResponse(
                {"detail": {"code": code, "message": message}}, status_code=status, headers=headers
            )(scope, receive, secure_send)

        if is_admin_api:
            try:
                settings = AdminSettings()
            except ValidationError:
                await reject(503, "ADMIN_DISABLED", "관리자 인증 설정이 완료되지 않았습니다.")
                return
            headers = Headers(scope=scope)
            origins = headers.getlist("origin")
            mutation = scope["method"] not in {"GET", "HEAD"}
            if (
                len(origins) > 1
                or any(origin != settings.canonical_origin for origin in origins)
                or (mutation and origins != [settings.canonical_origin])
            ):
                await reject(403, "FORBIDDEN", "허용되지 않은 출처의 관리자 요청입니다.")
                return
            if scope["method"] == "OPTIONS":
                await reject(403, "FORBIDDEN", "관리자 API는 외부 출처 요청을 허용하지 않습니다.")
                return
            if mutation:
                limiter = getattr(scope["app"].state, "admin_limiter", None)
                client = (scope.get("client") or ("unknown", 0))[0]
                if limiter is None or not limiter.allow(client):
                    await reject(
                        429,
                        "RATE_LIMITED",
                        "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                        {"Retry-After": "60"},
                    )
                    return
                if (
                    headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                ):
                    await reject(415, "INVALID_REQUEST", "JSON 형식으로 요청해 주세요.")
                    return
                body = bytearray()
                try:
                    async for chunk in Request(scope, receive).stream():
                        body.extend(chunk)
                        if len(body) > MAX_ADMIN_BODY:
                            await reject(
                                413, "INVALID_REQUEST", "관리자 요청의 크기가 너무 큽니다."
                            )
                            return
                except (ClientDisconnect, asyncio.CancelledError):
                    return
                original_receive = receive
                delivered = False

                async def replay_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await original_receive()

                receive = replay_receive
        await self.app(scope, receive, secure_send)
