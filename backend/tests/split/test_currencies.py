"""Sanity checks on shared/currencies.json (also read by the iOS app)."""

import json
import re

from app.services.split_engine import currency


def _table() -> list[dict]:
    return json.loads(currency.CURRENCIES_PATH.read_text(encoding="utf-8"))["currencies"]


def test_known_decimals() -> None:
    assert currency.decimals("SGD") == 2
    assert currency.decimals("JPY") == 0
    assert currency.decimals("KWD") == 3
    assert currency.decimals("INR") == 2
    assert currency.decimals("VND") == 0


def test_only_real_money() -> None:
    for code in ["XAU", "XAG", "XTS", "XXX", "XDR", "CLF", "USN", "BOV"]:
        assert not currency.is_supported(code), code


def test_table_shape() -> None:
    rows = _table()
    codes = [r["code"] for r in rows]
    assert len(rows) >= 150
    assert codes == sorted(set(codes)), "sorted and unique"
    for r in rows:
        assert re.fullmatch(r"[A-Z]{3}", r["code"])
        assert r["decimals"] in (0, 2, 3)
        assert r["name"] and r["countries"], r["code"]  # the iOS search box needs these
