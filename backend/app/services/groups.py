"""Groups, members, invites and join requests (PRD section 9; decisions of 2026-11-17/18).

Rules enforced here:
- Every member is equal: there are no admins (like Splitwise). Any member can add their
  own friends, remove someone, change settings (including Smart Settle), archive or
  unarchive, turn off any invite link, and approve or decline join requests.
- Only current members can see a group (others get 404, as if it didn't exist).
- Joining (added, by link, or approved) makes you friends with every current member.
- Nobody leaves or is removed while they owe or are owed money in the group.
- Archived groups are read-only until a member unarchives them.
- Membership changes lock the group row, so they happen one at a time.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import pagination
from app.core.errors import ProblemError
from app.models import FriendSource, Group, GroupInvite, GroupJoinRequest, GroupMember, User
from app.models.group import JoinRequestStatus
from app.repositories import friends as friend_repo
from app.repositories import groups as repo
from app.repositories import users as user_repo
from app.schemas.groups import GroupCreateIn, GroupPatchIn
from app.services.balances import member_balance

INVITE_LIFETIME = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class GroupDetail:
    group: Group
    members: list[tuple[GroupMember, User]]


@dataclass(frozen=True, slots=True)
class GroupListEntry:
    group: Group
    member_count: int


@dataclass(frozen=True, slots=True)
class GroupPage:
    items: list[GroupListEntry]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class InvitePreview:
    invite: GroupInvite
    group: Group
    member_count: int
    already_member: bool


@dataclass(frozen=True, slots=True)
class AcceptResult:
    status: str  # joined | pending | already_member
    group_id: uuid.UUID
    request_id: uuid.UUID | None


class GroupService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Groups ---------------------------------------------------------------------------

    async def create(self, user: User, body: GroupCreateIn) -> GroupDetail:
        _require_name(user)
        # Keep the order the person picked (duplicates and themselves dropped).
        ordered = [u for u in dict.fromkeys(body.member_ids) if u != user.id]
        others = set(ordered)
        await self._check_addable(user, others)
        group = await repo.create(
            self._session,
            name=body.name,
            type=body.type,
            default_currency=body.default_currency,
            simplify_debts=body.smart_settle,
            created_by=user.id,
        )
        await repo.add_member(self._session, group.id, user.id)
        for uid in ordered:
            await repo.add_member(self._session, group.id, uid)
        await self._befriend({user.id} | others, newly_added={user.id} | others)
        await self._session.commit()
        return await self._detail(group.id, user)

    async def page(
        self, user: User, *, archived: bool, limit: int, cursor: str | None
    ) -> GroupPage:
        after = pagination.decode(cursor) if cursor else None
        rows = await repo.my_groups(
            self._session, user.id, archived=archived, limit=limit + 1, after=after
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        counts = await repo.member_counts(self._session, [g.id for g in rows])
        items = [GroupListEntry(g, counts.get(g.id, 0)) for g in rows]
        next_cursor = None
        if has_more:
            last = rows[-1]
            next_cursor = pagination.encode(last.created_at, last.id)
        return GroupPage(items=items, next_cursor=next_cursor)

    async def get(self, user: User, group_id: uuid.UUID) -> GroupDetail:
        await self._member(user, group_id)
        return await self._detail(group_id, user)

    async def update(self, user: User, group_id: uuid.UUID, body: GroupPatchIn) -> GroupDetail:
        group, _ = await self._locked_member(user, group_id)
        _require_active(group)
        if body.name is not None:
            group.name = body.name
        if body.type is not None:
            group.type = body.type
        if body.default_currency is not None:
            group.default_currency = body.default_currency
        if body.smart_settle is not None:
            group.simplify_debts = body.smart_settle
        await self._session.commit()
        return await self._detail(group_id, user)

    async def set_archived(self, user: User, group_id: uuid.UUID, archived: bool) -> GroupDetail:
        group, _ = await self._locked_member(user, group_id)
        if archived and group.archived_at is None:
            group.archived_at = datetime.now(UTC)
        elif not archived:
            group.archived_at = None
        await self._session.commit()
        return await self._detail(group_id, user)

    # --- Members --------------------------------------------------------------------------

    async def add_members(
        self, user: User, group_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> GroupDetail:
        _require_name(user)
        group, _ = await self._locked_member(user, group_id)
        _require_active(group)
        current = {m.user_id for m, _ in await repo.members(self._session, group_id)}
        wanted = set(user_ids)
        already = sorted(str(u) for u in wanted & current)
        if already:
            raise ProblemError(
                422,
                "already-member",
                "Some of these people are already in the group.",
                errors=[{"user_id": u} for u in already],
            )
        await self._check_addable(user, wanted)
        for uid in dict.fromkeys(user_ids):  # in the order given
            await repo.add_member(self._session, group_id, uid)
        await self._befriend(current | wanted, newly_added=wanted)  # type: ignore[arg-type]
        await self._session.commit()
        return await self._detail(group_id, user)

    async def remove(self, user: User, group_id: uuid.UUID, target_id: uuid.UUID) -> None:
        """Remove someone, or leave (removing yourself). Any member can do either."""
        group, me = await self._locked_member(user, group_id)
        _require_active(group)
        target = (
            me
            if target_id == user.id
            else await repo.membership(self._session, group_id, target_id)
        )
        if target is None:
            raise ProblemError(404, "not-found", "That person isn't in this group.")
        owed = await member_balance(self._session, group_id, target_id)
        if owed:
            who = "You" if target_id == user.id else "They"
            raise ProblemError(
                409,
                "balance-not-zero",
                f"{who} still owe or are owed money in this group. Settle up first.",
                errors=[{"currency": c, "amount_minor": a} for c, a in owed.items()],
            )
        target.left_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.commit()

    # --- Invites --------------------------------------------------------------------------

    async def create_invite(
        self, user: User, group_id: uuid.UUID, requires_approval: bool
    ) -> GroupInvite:
        group, _ = await self._locked_member(user, group_id)
        _require_active(group)
        invite = await repo.create_invite(
            self._session,
            group_id,
            user.id,
            requires_approval,
            datetime.now(UTC) + INVITE_LIFETIME,
        )
        await self._session.commit()
        return invite

    async def revoke_invite(self, user: User, group_id: uuid.UUID, token: str) -> None:
        await self._locked_member(user, group_id)
        invite = await repo.get_invite(self._session, token)
        if invite is None or invite.group_id != group_id:
            raise ProblemError(404, "not-found", "Invite link not found.")
        if invite.revoked_at is None:
            invite.revoked_at = datetime.now(UTC)
        await self._session.commit()

    async def preview(self, user: User, token: str) -> InvitePreview:
        invite, group = await self._usable_invite(token)
        counts = await repo.member_counts(self._session, [group.id])
        mine = await repo.membership(self._session, group.id, user.id)
        return InvitePreview(invite, group, counts.get(group.id, 0), mine is not None)

    async def accept(self, user: User, token: str) -> AcceptResult:
        _require_name(user)
        invite, group = await self._usable_invite(token)
        group = await repo.get(self._session, group.id, lock=True)  # type: ignore[assignment]
        _require_active(group)
        if await repo.membership(self._session, group.id, user.id):
            return AcceptResult("already_member", group.id, None)
        if invite.requires_approval:
            request = await repo.pending_request(self._session, group.id, user.id)
            if request is None:
                request = await repo.create_request(self._session, group.id, user.id, token)
                await self._session.commit()
            return AcceptResult("pending", group.id, request.id)
        await self._join(group.id, user.id)
        await self._session.commit()
        return AcceptResult("joined", group.id, None)

    # --- Join requests --------------------------------------------------------------------

    async def join_requests(
        self, user: User, group_id: uuid.UUID
    ) -> list[tuple[GroupJoinRequest, User]]:
        await self._member(user, group_id)
        return await repo.pending_requests(self._session, group_id)

    async def decide(
        self, user: User, group_id: uuid.UUID, request_id: uuid.UUID, approve: bool
    ) -> None:
        group, _ = await self._locked_member(user, group_id)
        _require_active(group)
        request = await repo.get_request(self._session, request_id)
        if request is None or request.group_id != group_id:
            raise ProblemError(404, "not-found", "Join request not found.")
        if request.status is not JoinRequestStatus.PENDING:
            raise ProblemError(409, "already-decided", "This request was already answered.")
        request.status = JoinRequestStatus.APPROVED if approve else JoinRequestStatus.DECLINED
        request.decided_by = user.id
        request.decided_at = datetime.now(UTC)
        if approve and not await repo.membership(self._session, group_id, request.user_id):
            await self._join(group_id, request.user_id)
        await self._session.commit()

    # --- Helpers --------------------------------------------------------------------------

    async def _member(self, user: User, group_id: uuid.UUID) -> GroupMember:
        me = await repo.membership(self._session, group_id, user.id)
        if me is None:
            raise ProblemError(404, "not-found", "Group not found.")
        return me

    async def _locked_member(self, user: User, group_id: uuid.UUID) -> tuple[Group, GroupMember]:
        group = await repo.get(self._session, group_id, lock=True)
        me = await repo.membership(self._session, group_id, user.id) if group else None
        if group is None or me is None:
            raise ProblemError(404, "not-found", "Group not found.")
        return group, me

    async def _usable_invite(self, token: str) -> tuple[GroupInvite, Group]:
        invite = await repo.get_invite(self._session, token)
        group = await repo.get(self._session, invite.group_id) if invite else None
        if invite is None or group is None:
            raise ProblemError(404, "not-found", "This invite link doesn't exist.")
        if invite.revoked_at is not None:
            raise ProblemError(410, "invite-revoked", "This invite link was turned off.")
        if invite.expires_at <= datetime.now(UTC):
            raise ProblemError(410, "invite-expired", "This invite link has expired.")
        return invite, group

    async def _join(self, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
        current = {m.user_id for m, _ in await repo.members(self._session, group_id)}
        await repo.add_member(self._session, group_id, user_id)
        await self._befriend(current | {user_id}, newly_added={user_id})  # type: ignore[arg-type]

    async def _check_addable(self, user: User, people: set[uuid.UUID]) -> None:
        """People added directly must exist, have a name and be the adder's friends."""
        if not people:
            return
        users = await user_repo.get_users(self._session, people)
        unknown = sorted(str(p) for p in people - users.keys())
        if unknown:
            raise ProblemError(
                422,
                "unknown-user",
                "Some of these people don't have a SpendIt account.",
                errors=[{"user_id": u} for u in unknown],
            )
        nameless = sorted(str(u.id) for u in users.values() if u.display_name is None)
        if nameless:
            raise ProblemError(
                422,
                "name-required",
                "Some of these people haven't finished signing up (no name yet).",
                errors=[{"user_id": u} for u in nameless],
            )
        friends = await friend_repo.friends_among(self._session, user.id, people)
        strangers = sorted(str(p) for p in people - friends)
        if strangers:
            raise ProblemError(
                422,
                "not-friends",
                "You can only add your friends. Share an invite link with anyone else.",
                errors=[{"user_id": s} for s in strangers],
            )

    async def _befriend(self, everyone: set[uuid.UUID], *, newly_added: set[uuid.UUID]) -> None:
        """Joining makes you friends with every member (source "group"). Only pairs
        involving a newcomer are created, so nobody is re-friended against their wishes."""
        pairs = {(a, b) for a in newly_added for b in everyone if a != b}
        await friend_repo.connect_many(self._session, pairs, FriendSource.GROUP)

    async def _detail(self, group_id: uuid.UUID, user: User) -> GroupDetail:
        group = await repo.get(self._session, group_id)
        members = await repo.members(self._session, group_id)
        return GroupDetail(group=group, members=members)  # type: ignore[arg-type]


def _require_name(user: User) -> None:
    if user.display_name is None:
        raise ProblemError(
            422, "name-required", "Set your name first, so friends know who you are."
        )


def _require_active(group: Group) -> None:
    if group.archived_at is not None:
        raise ProblemError(409, "group-archived", "This group is archived. Unarchive it first.")
