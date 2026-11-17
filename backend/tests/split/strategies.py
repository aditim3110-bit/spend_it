"""Hypothesis generators for random *valid* split requests."""

from hypothesis import strategies as st

from app.services.split_engine import Payer, ShareInput, SplitMode, SplitRequest
from app.services.split_engine.limits import (
    MAX_PARTICIPANTS,
    MAX_SHARE_WEIGHT,
    MAX_TOTAL,
    PERCENT_TOTAL,
)

ids = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12)
currencies = st.sampled_from(["SGD", "JPY", "KWD", "USD", "INR", "IDR"])
# Mostly everyday amounts, sometimes up to the S$100 billion cap.
totals = st.one_of(st.integers(1, 1_000_000), st.integers(1, MAX_TOTAL))


@st.composite
def partition(draw: st.DrawFn, total: int, parts: int, min_part: int = 0) -> list[int]:
    """Split `total` into `parts` integers >= min_part that add up exactly to total."""
    spare = total - parts * min_part
    cuts = sorted(draw(st.lists(st.integers(0, spare), min_size=parts - 1, max_size=parts - 1)))
    bounds = [0, *cuts, spare]
    return [min_part + bounds[i + 1] - bounds[i] for i in range(parts)]


@st.composite
def split_requests(draw: st.DrawFn, mode: SplitMode | None = None) -> SplitRequest:
    mode = mode or draw(st.sampled_from(list(SplitMode)))
    total = draw(totals)
    n = draw(st.integers(1, MAX_PARTICIPANTS) | st.integers(1, 6))
    people = draw(st.lists(ids, min_size=n, max_size=n, unique=True))

    if mode is SplitMode.EQUAL:
        values: list[int | None] = [None] * n
    elif mode is SplitMode.EXACT:
        values = list(draw(partition(total, n)))
    elif mode is SplitMode.PERCENT:
        values = list(draw(partition(PERCENT_TOTAL, n)))
    else:
        values = draw(st.lists(st.integers(0, MAX_SHARE_WEIGHT), min_size=n, max_size=n))
        if not any(values):
            values[0] = 1

    # Payers: usually one of the participants, sometimes an outsider, sometimes several.
    candidates = list(dict.fromkeys(people + draw(st.lists(ids, max_size=3))))
    k = draw(st.integers(1, min(total, 5, len(candidates))))
    payer_ids = draw(st.lists(st.sampled_from(candidates), min_size=k, max_size=k, unique=True))
    amounts = draw(partition(total, len(payer_ids), min_part=1))

    return SplitRequest(
        total=total,
        currency=draw(currencies),
        payers=tuple(Payer(p, a) for p, a in zip(payer_ids, amounts, strict=True)),
        mode=mode,
        inputs=tuple(ShareInput(p, v) for p, v in zip(people, values, strict=True)),
    )
