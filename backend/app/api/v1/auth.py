"""Sign-in routes (PRD sections 6 and 17).

No Idempotency-Key here: there's no user yet to scope one to. These routes are protected
by the OTP rate limits and refresh-token rotation instead.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import client_ip, get_auth_service, get_otp_service, get_settings
from app.api.v1.me import me_out
from app.core.config import Settings
from app.schemas.auth import (
    OtpSendIn,
    OtpSendOut,
    OtpVerifyIn,
    RefreshIn,
    SessionOut,
    TokensOut,
)
from app.services.auth.identity import normalise
from app.services.auth.otp import OtpService
from app.services.auth.service import AuthService, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/send", status_code=status.HTTP_202_ACCEPTED, response_model=OtpSendOut)
async def send_code(
    body: OtpSendIn,
    request: Request,
    otp: Annotated[OtpService, Depends(get_otp_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OtpSendOut:
    """Send a 6-digit code. The reply is the same whether or not an account exists, so
    nobody can use this to check if a phone number is registered."""
    value = normalise(body.kind, body.value, body.region or settings.default_phone_region)
    await otp.send(body.kind, value, client_ip(request))
    return OtpSendOut()


@router.post("/otp/verify", response_model=SessionOut)
async def verify_code(
    body: OtpVerifyIn,
    otp: Annotated[OtpService, Depends(get_otp_service)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionOut:
    """Check the code, then sign in (or create the account on first use)."""
    value = normalise(body.kind, body.value, body.region or settings.default_phone_region)
    await otp.check(value, body.code)
    result = await auth.sign_in(body.kind, value, body.device.device_id, body.device.platform)
    return SessionOut(
        **_tokens(result.tokens).model_dump(),
        is_new_user=result.is_new_user,
        user=me_out(result.user),
    )


@router.post("/refresh", response_model=TokensOut)
async def refresh(
    body: RefreshIn, auth: Annotated[AuthService, Depends(get_auth_service)]
) -> TokensOut:
    """Swap a renewal pass for a new badge and a new pass."""
    return _tokens(await auth.refresh(body.refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshIn, auth: Annotated[AuthService, Depends(get_auth_service)]
) -> Response:
    await auth.sign_out(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _tokens(pair: TokenPair) -> TokensOut:
    return TokensOut(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
        refresh_expires_in=pair.refresh_expires_in,
    )
