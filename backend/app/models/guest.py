"""Guests: friends without the app who join through a link (PRD section 15)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, text_enum
from app.models.user import IdentifierKind


class GuestIdentity(IdMixin, CreatedAtMixin, Base):
    """One guest spot on a bill (PRD section 15).

    The payer adds an unnamed spot ("Guest 1"). The spot stays empty until a guest opens the
    bill's shared link, types their own name, and verifies a phone/email by OTP. Then
    display_name, the identifier and verified_at are filled in. The same person gets a
    separate row on each bill, so the identifier is not unique.

    When someone signs up with a phone/email matching verified guest rows, they confirm it's
    them by typing their name. If it matches, merged_user_id is set and all their past bills
    appear; old expense rows are never rewritten. After 3 wrong names, merge_blocked_at is
    set and they're pointed to support. The bills stay with the guest, so no debt disappears.
    """

    __tablename__ = "guest_identities"

    display_name: Mapped[str | None] = mapped_column(String(80))  # empty until filled
    identifier_kind: Mapped[IdentifierKind | None] = mapped_column(
        text_enum(IdentifierKind, "guest_identifier_kind")
    )
    identifier_normalised: Mapped[str | None] = mapped_column(Text, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    merged_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merge_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "(identifier_kind IS NULL) = (identifier_normalised IS NULL)",
            name="identifier_complete",
        ),
        CheckConstraint(
            "(merged_user_id IS NULL) = (merged_at IS NULL)", name="merge_fields_together"
        ),
        CheckConstraint(
            "merged_user_id IS NULL OR merge_blocked_at IS NULL", name="merged_or_blocked"
        ),
        CheckConstraint("char_length(btrim(display_name)) > 0", name="display_name_not_blank"),
        # A filled (verified) spot always has the guest's own name and phone/email.
        CheckConstraint(
            "verified_at IS NULL OR "
            "(display_name IS NOT NULL AND identifier_normalised IS NOT NULL)",
            name="verified_spot_complete",
        ),
        # Only spots the guest verified themselves can be merged into an account.
        CheckConstraint(
            "merged_user_id IS NULL OR verified_at IS NOT NULL", name="merge_needs_verified"
        ),
    )
