"""Currency decimals from the shared ISO 4217 table (<repo>/shared/currencies.json).

The iOS app reads the same file, so both sides always agree on decimals.
"""

import json
from functools import cache
from pathlib import Path

CURRENCIES_PATH = Path(__file__).resolve().parents[4] / "shared" / "currencies.json"


@cache
def _decimals() -> dict[str, int]:
    data = json.loads(CURRENCIES_PATH.read_text(encoding="utf-8"))
    return {c["code"]: c["decimals"] for c in data["currencies"]}


def is_supported(code: str) -> bool:
    return code in _decimals()


def decimals(code: str) -> int:
    """Number of minor-unit digits: SGD 2, JPY 0, KWD 3. KeyError if unsupported."""
    return _decimals()[code]
