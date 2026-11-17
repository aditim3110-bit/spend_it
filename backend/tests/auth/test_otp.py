"""One-time codes: sign-up, sign-in, wrong codes, expiry and rate limits (PRD section 6)."""

from redis.asyncio import Redis

from app.services.auth.otp import CODE_TTL_SECONDS, email_subject, message_text
from tests.auth.conftest import PHONE, TEST_REDIS_URL, Api


async def test_first_sign_in_creates_an_account_without_a_name(api: Api) -> None:
    body = await api.sign_in()
    assert body["is_new_user"] is True
    assert body["user"]["display_name"] is None
    assert body["user"]["needs_name"] is True  # app shows "What should friends call you?"
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["refresh_expires_in"] == 30 * 24 * 60 * 60


async def test_signing_in_again_returns_the_same_account(api: Api) -> None:
    first = await api.sign_in()
    second = await api.sign_in()
    assert second["is_new_user"] is False
    assert second["user"]["id"] == first["user"]["id"]


async def test_local_and_international_formats_are_the_same_phone(api: Api) -> None:
    first = await api.sign_in("+65 9123 4567")
    second = await api.sign_in("9123 4567")  # typed locally, region defaults to SG
    assert second["user"]["id"] == first["user"]["id"]
    assert api.sender.sent[-1][1] == PHONE  # codes go to the canonical E.164 number


async def test_email_ignores_capital_letters_only(api: Api) -> None:
    first = await api.sign_in("Aditi@Example.com", kind="email")
    second = await api.sign_in("aditi@example.com", kind="email")
    assert second["user"]["id"] == first["user"]["id"]
    dotted = await api.sign_in("a.diti@example.com", kind="email")
    assert dotted["user"]["id"] != first["user"]["id"]  # dots are kept, as decided


async def test_invalid_phone_and_email_are_rejected(api: Api) -> None:
    r = await api.send_code("12")
    assert r.status_code in (422,)
    assert r.headers["content-type"] == "application/problem+json"
    r = await api.send_code("not-an-email", kind="email")
    assert r.status_code == 422
    assert r.json()["type"].endswith("/invalid-email")


async def test_wrong_code_counts_down_then_locks(api: Api) -> None:
    await api.send_code()
    right = api.sender.last_code()
    wrong = "000000" if right != "000000" else "111111"
    for left in (4, 3, 2, 1):
        r = await api.verify(code=wrong)
        assert r.status_code == 400
        assert r.json()["errors"] == [{"attempts_left": left}]
    r = await api.verify(code=wrong)  # 5th wrong guess
    assert r.json()["type"].endswith("/code-expired")
    r = await api.verify(code=right)  # even the right code no longer works
    assert r.json()["type"].endswith("/code-expired")


async def test_a_code_works_only_once(api: Api) -> None:
    await api.send_code()
    code = api.sender.last_code()
    assert (await api.verify(code=code)).status_code == 200
    r = await api.verify(code=code)
    assert r.json()["type"].endswith("/code-expired")


async def test_verify_without_requesting_a_code(api: Api) -> None:
    r = await api.verify(code="123456")
    assert r.status_code == 400
    assert r.json()["type"].endswith("/code-expired")


async def test_a_new_code_replaces_the_old_one(api: Api) -> None:
    await api.send_code()
    old = api.sender.last_code()
    await api.send_code()
    new = api.sender.last_code()
    if old != new:
        assert (await api.verify(code=old)).status_code == 400
    assert (await api.verify(code=new)).status_code == 200


async def test_three_codes_per_hour_per_phone(api: Api) -> None:
    for _ in range(3):
        assert (await api.send_code()).status_code == 202
    r = await api.send_code()
    assert r.status_code == 429
    assert r.headers["content-type"] == "application/problem+json"
    assert 0 < int(r.headers["retry-after"]) <= 3600


async def test_ten_codes_per_hour_per_ip(api: Api) -> None:
    for i in range(10):
        assert (await api.send_code(f"+659123450{i}")).status_code == 202
    r = await api.send_code("+6591234511")
    assert r.status_code == 429


async def test_redis_never_holds_the_raw_code_or_phone(api: Api) -> None:
    await api.send_code()
    code = api.sender.last_code()
    redis = Redis.from_url(TEST_REDIS_URL)
    try:
        keys = [k.decode() for k in await redis.keys("otp:code:*")]
        assert len(keys) == 1
        assert PHONE not in keys[0]
        stored = await redis.hget(keys[0], "code")
        assert stored is not None and stored.decode() != code
        ttl = await redis.ttl(keys[0])
        assert CODE_TTL_SECONDS - 5 <= ttl <= CODE_TTL_SECONDS
    finally:
        await redis.aclose()


async def test_unknown_fields_are_rejected(api: Api) -> None:
    r = await api.send_code(admin=True)
    assert r.status_code == 422


def test_message_is_formatted_for_one_tap_autofill() -> None:
    text = message_text("123456")
    assert text.startswith("123456 is your SpendIt code")
    assert text.endswith("@spendit.app #123456")  # standard origin-bound line
    assert email_subject("123456") == "123456 is your SpendIt code"
