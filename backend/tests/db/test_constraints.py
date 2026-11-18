"""Each test tries to save something the rules forbid and checks the database refuses.

These are the safety net under the service layer: even if a future bug slips past the
Python checks, the database itself won't store a broken ledger.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

NOW = "now()"
DAY = date(2026, 11, 17)


async def insert(conn: AsyncConnection, table: str, **values: Any) -> uuid.UUID:
    cols = ", ".join(values)
    params = ", ".join(NOW if v == NOW else f":{k}" for k, v in values.items())
    bind = {k: v for k, v in values.items() if v != NOW}
    sql = f"INSERT INTO {table} ({cols}) VALUES ({params}) RETURNING id"
    return (await conn.execute(text(sql), bind)).scalar_one()


@asynccontextmanager
async def rejected(conn: AsyncConnection, match: str | None = None) -> AsyncIterator[None]:
    """Expect the statement inside to be refused; roll back just that statement."""
    savepoint = await conn.begin_nested()
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        yield
    await savepoint.rollback()


async def user(conn: AsyncConnection, name: str = "Aditi") -> uuid.UUID:
    return await insert(conn, "users", display_name=name)


async def expense_with_revision(
    conn: AsyncConnection, creator: uuid.UUID, friend: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """A complete, valid S$10.00 expense, written in the order the service layer will use."""
    expense = await insert(
        conn,
        "expenses",
        kind="expense",
        context_type="direct",
        expense_date=DAY,
        created_by=creator,
    )
    revision = await insert(
        conn,
        "expense_revisions",
        expense_id=expense,
        rev_no=1,
        context_type="direct",
        name="Dinner",
        amount_minor=1000,
        currency="SGD",
        expense_date=DAY,
        split_mode="equal",
        reason="create",
        created_by=creator,
    )
    await insert(conn, "expense_payers", revision_id=revision, user_id=creator, amount_minor=1000)
    await insert(conn, "expense_shares", revision_id=revision, user_id=creator, owed_minor=500)
    await insert(conn, "expense_shares", revision_id=revision, user_id=friend, owed_minor=500)
    await conn.execute(
        text("UPDATE expenses SET current_revision_id = :r WHERE id = :e"),
        {"r": revision, "e": expense},
    )
    return expense, revision


# --- Expenses can actually be saved (the happy path works) ---------------------------


async def test_a_valid_expense_can_be_saved(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    expense, revision = await expense_with_revision(conn, a, b)
    current = (
        await conn.execute(
            text("SELECT current_revision_id FROM expenses WHERE id = :e"), {"e": expense}
        )
    ).scalar_one()
    assert current == revision


# --- The ledger is append-only (CLAUDE.md rule 4) ----------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE expense_revisions SET amount_minor = 999",
        "DELETE FROM expense_revisions",
        "UPDATE expense_payers SET amount_minor = 1",
        "DELETE FROM expense_payers",
        "UPDATE expense_shares SET owed_minor = 0",
        "DELETE FROM expense_shares",
        "TRUNCATE expense_shares CASCADE",
    ],
)
async def test_saved_history_cannot_be_changed(conn: AsyncConnection, sql: str) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    await expense_with_revision(conn, a, b)
    async with rejected(conn, match="append-only"):
        await conn.execute(text(sql))


async def test_expense_cannot_point_at_another_expenses_revision(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    expense_1, _ = await expense_with_revision(conn, a, b)
    _, revision_2 = await expense_with_revision(conn, a, b)
    async with rejected(conn, match="fk_expenses_current_revision"):
        await conn.execute(
            text("UPDATE expenses SET current_revision_id = :r WHERE id = :e"),
            {"r": revision_2, "e": expense_1},
        )


# --- Revisions ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "bad_value", "constraint"),
    [
        ("amount_minor", 0, "amount_range"),
        ("amount_minor", 10**13 + 1, "amount_range"),  # over the S$100 billion cap
        ("currency", "sgd", "currency_format"),
        ("split_mode", "magic", "split_mode"),
        ("name", "   ", "name_length"),
        ("notes", "x" * 2001, "notes_length"),
        ("context_type", "group", "context_matches_group"),  # group context but no group_id
    ],
)
async def test_bad_revision_values_are_rejected(
    conn: AsyncConnection, column: str, bad_value: Any, constraint: str
) -> None:
    a = await user(conn)
    expense = await insert(
        conn,
        "expenses",
        kind="expense",
        context_type="direct",
        expense_date=DAY,
        created_by=a,
    )
    good = dict(
        expense_id=expense,
        rev_no=1,
        context_type="direct",
        name="Dinner",
        amount_minor=1000,
        currency="SGD",
        expense_date=DAY,
        split_mode="equal",
        reason="create",
        created_by=a,
    )
    async with rejected(conn, match=constraint):
        await insert(conn, "expense_revisions", **{**good, column: bad_value})


async def test_revision_numbers_are_unique_per_expense(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    expense, _ = await expense_with_revision(conn, a, b)
    async with rejected(conn, match="uq_expense_revisions_expense_id_rev_no"):
        await insert(
            conn,
            "expense_revisions",
            expense_id=expense,
            rev_no=1,
            context_type="direct",
            name="Dinner again",
            amount_minor=1000,
            currency="SGD",
            expense_date=DAY,
            split_mode="equal",
            reason="edit",
            created_by=a,
        )


# --- Payers and shares ------------------------------------------------------------------


async def test_participant_is_exactly_one_of_user_or_guest(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    _, revision = await expense_with_revision(conn, a, b)
    guest = await insert(conn, "guest_identities", display_name="Chen", created_by=a)
    async with rejected(conn, match="user_xor_guest"):
        await insert(
            conn, "expense_shares", revision_id=revision, user_id=a, guest_id=guest, owed_minor=0
        )
    async with rejected(conn, match="user_xor_guest"):
        await insert(conn, "expense_shares", revision_id=revision, owed_minor=0)


async def test_same_person_cannot_pay_twice_in_one_revision(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    _, revision = await expense_with_revision(conn, a, b)
    async with rejected(conn, match="uq_expense_payers_revision_id_user_id"):
        await insert(conn, "expense_payers", revision_id=revision, user_id=a, amount_minor=1)


async def test_money_ranges(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    _, revision = await expense_with_revision(conn, a, b)
    c = await user(conn, "Chen")
    async with rejected(conn, match="owed_range"):
        await insert(conn, "expense_shares", revision_id=revision, user_id=c, owed_minor=-1)
    async with rejected(conn, match="amount_range"):
        await insert(conn, "expense_payers", revision_id=revision, user_id=c, amount_minor=0)


# --- Users and identifiers --------------------------------------------------------------


async def test_a_phone_number_belongs_to_one_account(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    await insert(
        conn,
        "user_identifiers",
        user_id=a,
        kind="phone",
        value_normalised="+6591234567",
        verified_at=NOW,
    )
    async with rejected(conn, match="uq_user_identifiers_value_normalised"):
        await insert(
            conn,
            "user_identifiers",
            user_id=b,
            kind="phone",
            value_normalised="+6591234567",
            verified_at=NOW,
        )


async def test_at_most_one_phone_and_one_email_per_user(conn: AsyncConnection) -> None:
    a = await user(conn)
    await insert(
        conn,
        "user_identifiers",
        user_id=a,
        kind="phone",
        value_normalised="+6591234567",
        verified_at=NOW,
        is_primary=True,
    )
    async with rejected(conn, match="uq_user_identifiers_user_id_kind"):
        await insert(
            conn,
            "user_identifiers",
            user_id=a,
            kind="phone",
            value_normalised="+6598765432",
            verified_at=NOW,
        )
    async with rejected(conn, match="uq_user_identifiers_one_primary"):
        await insert(
            conn,
            "user_identifiers",
            user_id=a,
            kind="email",
            value_normalised="aditi@example.com",
            verified_at=NOW,
            is_primary=True,
        )


async def test_display_name_may_be_empty_until_onboarding_but_not_blank(
    conn: AsyncConnection,
) -> None:
    await insert(conn, "users", default_currency="SGD")  # no name yet: allowed
    async with rejected(conn, match="display_name_not_blank"):
        await insert(conn, "users", display_name="  ")


# --- Guests -----------------------------------------------------------------------------


async def test_guest_cannot_be_both_merged_and_blocked(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    async with rejected(conn, match="merged_or_blocked"):
        await insert(
            conn,
            "guest_identities",
            display_name="Ben",
            created_by=a,
            identifier_kind="phone",
            identifier_normalised="+6590000001",
            verified_at=NOW,
            merged_user_id=b,
            merged_at=NOW,
            merge_blocked_at=NOW,
        )
    async with rejected(conn, match="merge_fields_together"):
        await insert(conn, "guest_identities", display_name="Ben", created_by=a, merged_user_id=b)


async def test_unnamed_spot_then_filled_by_the_guest(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    spot = await insert(conn, "guest_identities", created_by=a)  # "Guest 1": no name yet
    # Can't be marked verified without the guest's own name and phone/email...
    async with rejected(conn, match="verified_spot_complete"):
        await conn.execute(
            text("UPDATE guest_identities SET verified_at = now() WHERE id = :g"), {"g": spot}
        )
    # ...and can't be merged into an account before it's verified.
    async with rejected(conn, match="merge_needs_verified"):
        await conn.execute(
            text(
                "UPDATE guest_identities SET merged_user_id = :u, merged_at = now() WHERE id = :g"
            ),
            {"u": b, "g": spot},
        )
    await conn.execute(
        text(
            "UPDATE guest_identities SET display_name = 'Chen', identifier_kind = 'phone', "
            "identifier_normalised = '+6590000000', verified_at = now() WHERE id = :g"
        ),
        {"g": spot},
    )


async def test_two_payers_can_add_the_same_guest(conn: AsyncConnection) -> None:
    a, b = await user(conn), await user(conn, "Ben")
    for creator in (a, b):
        await insert(
            conn,
            "guest_identities",
            display_name="Chen",
            created_by=creator,
            identifier_kind="phone",
            identifier_normalised="+6590000000",
        )


# --- Groups -----------------------------------------------------------------------------


async def test_group_membership_rules(conn: AsyncConnection) -> None:
    a = await user(conn)
    group = await insert(
        conn,
        "groups",
        name="Bali 2027",
        type="trip",
        default_currency="SGD",
        simplify_debts=True,
        created_by=a,
    )
    member = await insert(conn, "group_members", group_id=group, user_id=a)

    # Can't be a current member twice...
    async with rejected(conn, match="uq_group_members_active_user"):
        await insert(conn, "group_members", group_id=group, user_id=a)
    # ...but can rejoin after leaving (history is kept as a separate row).
    await conn.execute(
        text("UPDATE group_members SET left_at = now() WHERE id = :m"), {"m": member}
    )
    await insert(conn, "group_members", group_id=group, user_id=a)
    async with rejected(conn, match="group_type"):
        await insert(
            conn,
            "groups",
            name="X",
            type="party",
            default_currency="SGD",
            simplify_debts=True,
            created_by=a,
        )


# --- Retry tickets ----------------------------------------------------------------------


async def test_retry_ticket_is_unique_per_user(conn: AsyncConnection) -> None:
    a = await user(conn)
    key = uuid.uuid4()
    row = dict(
        user_id=a,
        key=key,
        method="POST",
        path="/v1/expenses",
        request_hash="a" * 64,
        expires_at=NOW,
    )
    await conn.execute(
        text(
            "INSERT INTO idempotency_keys (user_id, key, method, path, request_hash, expires_at)"
            " VALUES (:user_id, :key, :method, :path, :request_hash, now())"
        ),
        {k: v for k, v in row.items() if k != "expires_at"},
    )
    async with rejected(conn, match="pk_idempotency_keys"):
        await conn.execute(
            text(
                "INSERT INTO idempotency_keys (user_id, key, method, path, request_hash,"
                " expires_at) VALUES (:user_id, :key, 'POST', '/v1/expenses', :h, now())"
            ),
            {"user_id": a, "key": key, "h": "b" * 64},
        )


# --- Friends ------------------------------------------------------------------------------


async def test_friendship_is_stored_once_per_pair(conn: AsyncConnection) -> None:
    a, b = sorted([await user(conn), await user(conn, "Ben")])
    await conn.execute(
        text("INSERT INTO friendships (user_a, user_b, source) VALUES (:a, :b, 'qr')"),
        {"a": a, "b": b},
    )
    async with rejected(conn, match="ordered_pair"):  # reversed order is refused
        await conn.execute(
            text("INSERT INTO friendships (user_a, user_b, source) VALUES (:b, :a, 'qr')"),
            {"a": a, "b": b},
        )
    async with rejected(conn, match="pk_friendships"):
        await conn.execute(
            text("INSERT INTO friendships (user_a, user_b, source) VALUES (:a, :b, 'nearby')"),
            {"a": a, "b": b},
        )


async def test_one_active_qr_code_per_user(conn: AsyncConnection) -> None:
    a = await user(conn)
    await insert(conn, "user_qr_codes", user_id=a, code="A" * 22)
    async with rejected(conn, match="uq_user_qr_codes_one_active"):
        await insert(conn, "user_qr_codes", user_id=a, code="B" * 22)
    async with rejected(conn, match="code_format"):
        await insert(conn, "user_qr_codes", user_id=a, code="short", revoked_at=NOW)
