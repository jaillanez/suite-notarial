"""Cookies de sesión: HttpOnly siempre, Secure según entorno, SameSite y rutas mínimas."""

from fastapi import Response

from app.core.config import Settings

ACCESS_COOKIE = "sn_access"
REFRESH_COOKIE = "sn_refresh"
MFA_COOKIE = "sn_mfa"

ACCESS_PATH = "/api"
REFRESH_PATH = "/api/v1/auth"
MFA_PATH = "/api/v1/auth/login"


def _set(
    response: Response,
    settings: Settings,
    name: str,
    value: str,
    *,
    path: str,
    max_age: int,
    samesite: str,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=path,
        domain=settings.COOKIE_DOMAIN or None,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=samesite,  # type: ignore[arg-type]
    )


def set_access_cookie(response: Response, settings: Settings, access: str) -> None:
    _set(
        response,
        settings,
        ACCESS_COOKIE,
        access,
        path=ACCESS_PATH,
        max_age=settings.JWT_ACCESS_TTL_MIN * 60,
        samesite="lax",
    )


def set_session_cookies(response: Response, settings: Settings, access: str, refresh: str) -> None:
    set_access_cookie(response, settings, access)
    _set(
        response,
        settings,
        REFRESH_COOKIE,
        refresh,
        path=REFRESH_PATH,
        max_age=settings.JWT_REFRESH_TTL_DAYS * 86400,
        samesite="strict",
    )
    clear_mfa_cookie(response, settings)


def set_mfa_cookie(response: Response, settings: Settings, token: str) -> None:
    _set(
        response,
        settings,
        MFA_COOKIE,
        token,
        path=MFA_PATH,
        max_age=settings.MFA_PENDING_TTL_MIN * 60,
        samesite="strict",
    )


def clear_mfa_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        MFA_COOKIE, path=MFA_PATH, domain=settings.COOKIE_DOMAIN or None, httponly=True
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    domain = settings.COOKIE_DOMAIN or None
    response.delete_cookie(ACCESS_COOKIE, path=ACCESS_PATH, domain=domain, httponly=True)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, domain=domain, httponly=True)
    clear_mfa_cookie(response, settings)
