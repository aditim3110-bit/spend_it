"""POST /v1/split/preview: run the split engine without saving anything (PRD section 17)."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.errors import ProblemError
from app.core.split_errors import split_problem
from app.schemas.split import NetOut, ShareOut, SplitPreviewIn, SplitPreviewOut
from app.services.split_engine import (
    Payer,
    ShareInput,
    SplitError,
    SplitRequest,
    compute_split,
)

router = APIRouter(prefix="/split", tags=["split"])


@router.post("/preview", response_model=SplitPreviewOut)
async def preview(body: SplitPreviewIn, _: CurrentUser) -> SplitPreviewOut:
    request = SplitRequest(
        total=body.total,
        currency=body.currency,
        payers=tuple(Payer(p.id, p.amount) for p in body.payers),
        mode=body.mode,
        inputs=tuple(ShareInput(i.id, i.value) for i in body.inputs),
    )
    try:
        result = compute_split(request)
    except SplitError as err:
        raise split_problem(err) from None
    except ValueError as err:  # a value missing for exact/percent/shares
        raise ProblemError(422, "validation-error", str(err)) from None
    return SplitPreviewOut(
        total=result.total,
        currency=result.currency,
        mode=result.mode,
        shares=[ShareOut(id=s.id, owed=s.owed, input_value=s.input_value) for s in result.shares],
        nets=[NetOut(id=pid, net=net) for pid, net in result.nets().items()],
    )
