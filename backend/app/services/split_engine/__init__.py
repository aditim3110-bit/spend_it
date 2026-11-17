"""The split engine: pure Python, no web or database code. See PRD section 7."""

from app.services.split_engine.engine import compute_split
from app.services.split_engine.errors import SplitError
from app.services.split_engine.shortcuts import TwoPersonShortcut, two_person
from app.services.split_engine.types import (
    Payer,
    Share,
    ShareInput,
    SplitMode,
    SplitRequest,
    SplitResult,
)

__all__ = [
    "Payer",
    "Share",
    "ShareInput",
    "SplitError",
    "SplitMode",
    "SplitRequest",
    "SplitResult",
    "TwoPersonShortcut",
    "compute_split",
    "two_person",
]
