"""ORM models. Every model module must be imported here so Alembic can see it."""

from app.models.auth import Device, Platform, RefreshToken
from app.models.balance import Balance
from app.models.base import Base
from app.models.expense import Expense, ExpensePayer, ExpenseRevision, ExpenseShare
from app.models.friends import Friendship, FriendSource, UserQrCode
from app.models.group import Group, GroupMember
from app.models.guest import GuestIdentity
from app.models.idempotency import IdempotencyKey
from app.models.user import User, UserIdentifier

__all__ = [
    "Balance",
    "Base",
    "Device",
    "Expense",
    "ExpensePayer",
    "ExpenseRevision",
    "ExpenseShare",
    "FriendSource",
    "Friendship",
    "Group",
    "GroupMember",
    "GuestIdentity",
    "IdempotencyKey",
    "Platform",
    "RefreshToken",
    "User",
    "UserIdentifier",
    "UserQrCode",
]
