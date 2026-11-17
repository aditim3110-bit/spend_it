"""Turn whatever the user typed into one canonical phone number or email.

Phones become E.164 ("+6591234567"), so "9123 4567" typed in Singapore and
"+65 9123 4567" are the same account. Emails are trimmed and lowercased only; Gmail dots
and +tags are kept as typed (decided in Phase 0, see PRD section 6).
"""

import phonenumbers
from email_validator import EmailNotValidError, validate_email

from app.core.errors import ProblemError
from app.models.user import IdentifierKind


def normalise(kind: IdentifierKind, raw: str, region: str) -> str:
    if kind is IdentifierKind.PHONE:
        return normalise_phone(raw, region)
    return normalise_email(raw)


def normalise_phone(raw: str, region: str) -> str:
    try:
        number = phonenumbers.parse(raw, region.upper())
    except phonenumbers.NumberParseException:
        number = None
    if number is None or not phonenumbers.is_valid_number(number):
        raise ProblemError(422, "invalid-phone", "That doesn't look like a valid phone number.")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalise_email(raw: str) -> str:
    try:
        # Syntax check only; no network lookups during sign-in.
        result = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError:
        raise ProblemError(
            422, "invalid-email", "That doesn't look like a valid email address."
        ) from None
    return result.normalized.lower()
