"""Staying signed in: badges (access tokens), renewal passes (refresh tokens), the
10-second grace period, theft detection and signing out (PRD section 6)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.services.auth.tokens import create_access_token, hash_refresh_token
from tests.support.api import Api


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def refresh(api: Api, token: str):
    return await api.client.post("/v1/auth/refresh", json={"refresh_token": token})


# --- The badge (access token) --------------------------------------------------------


async def test_badge_opens_me(api: Api) -> None:
    session = await api.sign_in()
    r = await api.client.get("/v1/me", headers=auth(session["access_token"]))
    assert r.status_code == 200
    assert r.json()["id"] == session["user"]["id"]


async def test_no_badge_is_rejected_with_problem_json(api: Api) -> None:
    r = await api.client.get("/v1/me")
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"
    assert r.headers["www-authenticate"] == "Bearer"


async def test_tampered_badge_is_rejected(api: Api) -> None:
    session = await api.sign_in()
    token = session["access_token"]
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    r = await api.client.get("/v1/me", headers=auth(tampered))
    assert r.status_code == 401


async def test_expired_badge_is_rejected(api: Api) -> None:
    session = await api.sign_in()
    old = create_access_token(
        user_id=uuid.UUID(session["user"]["id"]),
        family_id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        secret=api.settings.jwt_secret.get_secret_value(),
        minutes=15,
        now=datetime.now(UTC) - timedelta(minutes=16),
    )
    assert (await api.client.get("/v1/me", headers=auth(old))).status_code == 401


async def test_unsigned_alg_none_badge_is_rejected(api: Api) -> None:
    """A classic attack: a token that claims it needs no signature."""
    session = await api.sign_in()
    forged = jwt.encode(
        {"sub": session["user"]["id"], "iss": "spendit", "aud": "spendit-api"},
        key=None,
        algorithm="none",
    )
    assert (await api.client.get("/v1/me", headers=auth(forged))).status_code == 401


async def test_badge_signed_with_another_key_is_rejected(api: Api) -> None:
    session = await api.sign_in()
    forged = create_access_token(
        user_id=uuid.UUID(session["user"]["id"]),
        family_id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        secret="someone-elses-secret-0123456789-abcdef",
        minutes=15,
    )
    assert (await api.client.get("/v1/me", headers=auth(forged))).status_code == 401


# --- The renewal pass (refresh token) --------------------------------------------------


async def test_refresh_gives_a_new_badge_and_a_new_pass(api: Api) -> None:
    session = await api.sign_in()
    r = await refresh(api, session["refresh_token"])
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != session["refresh_token"]
    assert (await api.client.get("/v1/me", headers=auth(new["access_token"]))).status_code == 200


async def test_reuse_within_10_seconds_is_allowed(api: Api) -> None:
    """The phone lost signal and retried with the same pass: not treated as theft."""
    session = await api.sign_in()
    first = await refresh(api, session["refresh_token"])
    retry = await refresh(api, session["refresh_token"])
    assert first.status_code == 200
    assert retry.status_code == 200
    # Both new passes keep working.
    assert (await refresh(api, first.json()["refresh_token"])).status_code == 200
    assert (await refresh(api, retry.json()["refresh_token"])).status_code == 200


async def test_reuse_after_10_seconds_signs_the_whole_session_out(api: Api, db_execute) -> None:
    session = await api.sign_in()
    newer = (await refresh(api, session["refresh_token"])).json()
    # Pretend the old pass was swapped 11 seconds ago.
    await db_execute(
        "UPDATE refresh_tokens SET used_at = now() - interval '11 seconds' WHERE token_hash = :h",
        h=hash_refresh_token(session["refresh_token"]),
    )
    r = await refresh(api, session["refresh_token"])  # someone replays the old pass
    assert r.status_code == 401
    assert r.json()["type"].endswith("/refresh-token-reused")
    # The newer pass, which the real phone holds, is now revoked too.
    r = await refresh(api, newer["refresh_token"])
    assert r.status_code == 401
    assert r.json()["type"].endswith("/invalid-refresh-token")


async def test_theft_on_one_device_does_not_sign_out_another(api: Api, db_execute) -> None:
    phone = await api.sign_in()
    # The same account signs in again (a second session).
    other = await api.sign_in()
    await refresh(api, phone["refresh_token"])
    await db_execute(
        "UPDATE refresh_tokens SET used_at = now() - interval '11 seconds' WHERE token_hash = :h",
        h=hash_refresh_token(phone["refresh_token"]),
    )
    assert (await refresh(api, phone["refresh_token"])).status_code == 401
    assert (await refresh(api, other["refresh_token"])).status_code == 200


async def test_expired_pass_is_rejected(api: Api, db_execute) -> None:
    session = await api.sign_in()
    await db_execute(
        "UPDATE refresh_tokens SET expires_at = now() - interval '1 second' WHERE token_hash = :h",
        h=hash_refresh_token(session["refresh_token"]),
    )
    r = await refresh(api, session["refresh_token"])
    assert r.status_code == 401


async def test_unknown_pass_is_rejected(api: Api) -> None:
    r = await refresh(api, "x" * 43)
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"


async def test_database_stores_only_hashes_of_passes(api: Api, db_execute) -> None:
    session = await api.sign_in()
    rows = await db_execute("SELECT token_hash FROM refresh_tokens")
    hashes = {r[0] for r in rows}
    assert session["refresh_token"] not in hashes
    assert hash_refresh_token(session["refresh_token"]) in hashes


async def test_sign_in_records_the_device_once(api: Api, db_execute) -> None:
    await api.sign_in()
    await api.sign_in()
    rows = await db_execute("SELECT client_device_id, platform FROM devices")
    assert rows == [("test-iphone-1", "ios")]


# --- Signing out -------------------------------------------------------------------------


async def test_logout_ends_the_session(api: Api) -> None:
    session = await api.sign_in()
    r = await api.client.post("/v1/auth/logout", json={"refresh_token": session["refresh_token"]})
    assert r.status_code == 204
    assert (await refresh(api, session["refresh_token"])).status_code == 401


async def test_logout_with_unknown_pass_still_succeeds(api: Api) -> None:
    r = await api.client.post("/v1/auth/logout", json={"refresh_token": "y" * 43})
    assert r.status_code == 204  # reveals nothing about which passes exist


# --- Settings safety ----------------------------------------------------------------------


def test_production_refuses_the_dev_secret() -> None:
    with pytest.raises(ValueError, match="SPENDIT_JWT_SECRET"):
        Settings(env="prod", jwt_secret="dev-only-insecure-secret-change-me-0123456789")
    with pytest.raises(ValueError, match="SPENDIT_JWT_SECRET"):
        Settings(env="prod", jwt_secret="too-short")
    Settings(env="prod", jwt_secret="a-real-secret-that-is-long-enough-1234567890")
