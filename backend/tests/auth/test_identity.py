"""Phone and email normalisation: the same person always maps to the same account."""

import phonenumbers
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.core.errors import ProblemError
from app.services.auth.identity import normalise_email, normalise_phone

REGIONS = ["SG", "IN", "MY", "ID", "US", "GB", "AU", "JP", "HK", "PH"]
FORMATS = [
    phonenumbers.PhoneNumberFormat.E164,
    phonenumbers.PhoneNumberFormat.INTERNATIONAL,
    phonenumbers.PhoneNumberFormat.NATIONAL,
]


@given(st.sampled_from(REGIONS), st.sampled_from(FORMATS))
def test_every_way_of_writing_a_number_gives_the_same_result(region: str, fmt: int) -> None:
    example = phonenumbers.example_number_for_type(region, phonenumbers.PhoneNumberType.MOBILE)
    canonical = phonenumbers.format_number(example, phonenumbers.PhoneNumberFormat.E164)
    typed = phonenumbers.format_number(example, fmt)
    assert normalise_phone(typed, region) == canonical
    assert normalise_phone(canonical, region) == canonical  # tidying twice changes nothing


@given(st.emails())
def test_email_normalisation_is_stable(email: str) -> None:
    try:
        once = normalise_email(email)
    except ProblemError:
        assume(False)  # some generated addresses are valid by RFC but not accepted; skip
    assert normalise_email(once) == once
    assert normalise_email(email.upper()) == once
    assert once == once.lower()


@pytest.mark.parametrize("raw", ["", "123", "+65 1234", "hello", "+999 12345678"])
def test_bad_phone_numbers_are_rejected(raw: str) -> None:
    with pytest.raises(ProblemError):
        normalise_phone(raw, "SG")
