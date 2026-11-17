"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ProblemError
from app.db.session import get_session
from app.models import User
from app.repositories import users as user_repo
from app.services.auth.otp import OtpService
from app.services.auth.service import AuthService
from app.services.auth.tokens import InvalidToken, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_otp_service(request: Request) -> OtpService:
    settings: Settings = request.app.state.settings
    return OtpService(
        request.app.state.redis,
        request.app.state.otp_sender,
        settings.jwt_secret.get_secret_value().encode(),
    )


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(session, settings)


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """Every route except /auth/* and /guest/* depends on this (PRD section 6)."""
    if credentials is None:
        raise _unauthorized("Sign in to continue.")
    try:
        claims = decode_access_token(
            credentials.credentials, settings.jwt_secret.get_secret_value()
        )
    except InvalidToken:
        raise _unauthorized("Your session has expired. Please sign in again.") from None
    user = await user_repo.get_user(session, claims.user_id)
    if user is None:
        raise _unauthorized("This account no longer exists.")
    return user


def client_ip(request: Request) -> str:
    # Behind a load balancer this must come from the trusted X-Forwarded-For header;
    # configured with uvicorn --proxy-headers when we deploy.
    return request.client.host if request.client else "unknown"


def _unauthorized(detail: str) -> ProblemError:
    return ProblemError(401, "unauthorized", detail, headers={"WWW-Authenticate": "Bearer"})


CurrentUser = Annotated[User, Depends(current_user)]
