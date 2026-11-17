"""Turn split engine errors into RFC 9457 problems. Used by the live preview and by saving
expenses, so the app sees the same error either way."""

import re

from app.core.errors import ProblemError
from app.services.split_engine import SplitError


def split_problem(err: SplitError) -> ProblemError:
    """A split error as RFC 9457 problem details. The type is the error code in
    kebab-case (e.g. .../percent-sum-invalid), and `errors` carries the offending
    participant and remainder, as PRD section 17 requires."""
    slug = re.sub(r"(?<!^)(?=[A-Z])", "-", err.code).lower()
    detail_fields = {
        "code": err.code,
        "side": err.side,
        "participant_id": err.participant_id,
        "remainder": err.remainder,
    }
    return ProblemError(
        422,
        slug,
        err.message,
        errors=[{k: v for k, v in detail_fields.items() if v is not None}],
    )
