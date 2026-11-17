"""Public web pages (no sign-in). Server-rendered with Jinja2, as PRD section 5 plans."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_settings
from app.core.config import Settings
from app.db.session import get_session
from app.repositories import friends as friends_repo

router = APIRouter(include_in_schema=False)  # web pages, not part of the API contract
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Don't let search engines index personal links, and keep the page out of frames.
PRIVATE_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@router.get("/u/{code}", response_class=HTMLResponse)
async def user_link(
    code: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """What someone sees after scanning a SpendIt QR code without the app installed.
    Shows the first name only: no phone, email, or anything else (PRD section 6A)."""
    owner = await friends_repo.owner_of_active_code(session, code)
    first_name = owner.display_name.split()[0] if owner and owner.display_name else None
    return templates.TemplateResponse(
        request,
        "user_link.html",
        {
            "first_name": first_name,
            "app_store_url": settings.app_store_url,
            "open_url": f"{settings.public_base_url}/u/{code}",
        },
        status_code=200 if first_name else 404,
        headers=PRIVATE_HEADERS,
    )
