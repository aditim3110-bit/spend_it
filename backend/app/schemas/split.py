"""Live split preview (POST /v1/split/preview): the same engine the server uses when it
saves, so what the app shows while typing is exactly what will be saved."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.services.split_engine import SplitMode
from app.services.split_engine.limits import MAX_PARTICIPANTS, MAX_PAYERS

# Lowercase IDs (canonical UUIDs, or temporary IDs for people not yet saved).
PersonId = Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,64}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayerIn(Strict):
    id: PersonId
    amount: int


class ShareInputIn(Strict):
    id: PersonId
    value: int | None = None


class SplitPreviewIn(Strict):
    total: int
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    payers: list[PayerIn] = Field(max_length=MAX_PAYERS + 1)
    mode: SplitMode
    inputs: list[ShareInputIn] = Field(max_length=MAX_PARTICIPANTS + 1)


class ShareOut(Strict):
    id: str
    owed: int
    input_value: int | None


class NetOut(Strict):
    id: str
    net: int  # paid minus owed: positive = others owe them


class SplitPreviewOut(Strict):
    total: int
    currency: str
    mode: SplitMode
    shares: list[ShareOut]
    nets: list[NetOut]
