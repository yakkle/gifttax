from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from backend.api.dependencies import admin_service
from backend.schemas.admin import (
    AdminConfig,
    AuthenticationFinish,
    CredentialSummary,
    LoginTokenInput,
    RegistrationFinish,
    RegistrationStart,
    SessionStatus,
    WebAuthnOptions,
)
from backend.services.admin_auth import CHALLENGE_SECONDS, AdminAuthService, CeremonyOptions
from backend.services.admin_sessions import SESSION_SECONDS, AdminAuthError, SessionGrant

admin_router = APIRouter(prefix="/api/admin/auth", tags=["관리자 인증"])
Service = Annotated[AdminAuthService, Depends(admin_service)]


def session_cookie(request: Request, service: AdminAuthService) -> str | None:
    return request.cookies.get(service.settings.session_cookie_name)


def csrf_header(request: Request) -> str | None:
    return request.headers.get("x-csrf-token")


def grant_session(
    response: Response, service: AdminAuthService, grant: SessionGrant
) -> SessionStatus:
    response.set_cookie(
        service.settings.session_cookie_name,
        grant.token,
        max_age=SESSION_SECONDS,
        secure=not service.settings.is_local_http,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.delete_cookie(
        service.settings.flow_cookie_name,
        secure=not service.settings.is_local_http,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return SessionStatus(csrf_token=grant.csrf_token, expires_at=grant.expires_at)


def grant_options(
    response: Response, service: AdminAuthService, options: CeremonyOptions
) -> WebAuthnOptions:
    response.set_cookie(
        service.settings.flow_cookie_name,
        options.flow_token,
        max_age=CHALLENGE_SECONDS,
        secure=not service.settings.is_local_http,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return WebAuthnOptions(challenge_id=options.challenge_id, options=options.options)


@admin_router.get("/config", response_model=AdminConfig)
def config(service: Service) -> AdminConfig:
    return AdminConfig(mode=service.settings.mode, has_passkey=service.has_credentials())


@admin_router.get("/session", response_model=SessionStatus)
def current_session(request: Request, service: Service) -> SessionStatus:
    session = service.sessions.authenticate(session_cookie(request, service))
    return SessionStatus(
        csrf_token=service.sessions.csrf_token(session.session_id), expires_at=session.expires_at
    )


@admin_router.post("/registration/options", response_model=WebAuthnOptions)
def registration_options(
    input_data: RegistrationStart, request: Request, response: Response, service: Service
) -> WebAuthnOptions:
    return grant_options(
        response,
        service,
        service.registration_options(
            input_data.registration_code, session_cookie(request, service), csrf_header(request)
        ),
    )


@admin_router.post("/registration/verify", response_model=SessionStatus)
def registration_verify(
    input_data: RegistrationFinish, request: Request, response: Response, service: Service
) -> SessionStatus:
    grant = service.register(
        input_data.challenge_id,
        input_data.credential,
        input_data.label,
        request.cookies.get(service.settings.flow_cookie_name),
        input_data.registration_code,
        session_cookie(request, service),
        csrf_header(request),
    )
    return grant_session(response, service, grant)


@admin_router.post("/authentication/options", response_model=WebAuthnOptions)
def authentication_options(response: Response, service: Service) -> WebAuthnOptions:
    return grant_options(response, service, service.authentication_options())


@admin_router.post("/authentication/verify", response_model=SessionStatus)
def authentication_verify(
    input_data: AuthenticationFinish, request: Request, response: Response, service: Service
) -> SessionStatus:
    grant = service.authenticate(
        input_data.challenge_id,
        input_data.credential,
        request.cookies.get(service.settings.flow_cookie_name),
    )
    return grant_session(response, service, grant)


@admin_router.post("/token/exchange", response_model=SessionStatus)
def token_exchange(
    input_data: LoginTokenInput, response: Response, service: Service
) -> SessionStatus:
    return grant_session(response, service, service.sessions.exchange_login_token(input_data.token))


@admin_router.post("/logout", status_code=204)
def logout(request: Request, response: Response, service: Service) -> None:
    service.sessions.logout(session_cookie(request, service), csrf_header(request))
    clear_cookies(response, service)


@admin_router.get("/credentials", response_model=list[CredentialSummary])
def credentials(request: Request, service: Service) -> list[CredentialSummary]:
    return service.list_credentials(session_cookie(request, service))


@admin_router.delete("/credentials/{credential_id}", status_code=204)
def delete_credential(
    credential_id: str, request: Request, response: Response, service: Service
) -> None:
    service.delete_credential(credential_id, session_cookie(request, service), csrf_header(request))
    clear_cookies(response, service)


def clear_cookies(response: Response, service: AdminAuthService) -> None:
    for name in (service.settings.session_cookie_name, service.settings.flow_cookie_name):
        response.delete_cookie(
            name,
            secure=not service.settings.is_local_http,
            httponly=True,
            samesite="strict",
            path="/",
        )


async def auth_error_handler(request: Request, error: AdminAuthError) -> JSONResponse:
    status = {
        "UNAUTHENTICATED": 401,
        "FORBIDDEN": 403,
        "INVALID_REQUEST": 400,
        "NOT_FOUND": 404,
        "CONFLICT": 409,
    }[error.code]
    return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=status)
