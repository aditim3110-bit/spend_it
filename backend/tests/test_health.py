import httpx

from tests.conftest import AppClient


async def test_liveness(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readiness_with_real_services(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/health/ready")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok"}


async def test_readiness_reports_broken_redis_as_problem(make_client: AppClient) -> None:
    # Nothing listens on port 1, so Redis is "down".
    async with make_client(redis_url="redis://localhost:1/0") as c:
        r = await c.get("/v1/health/ready")
    assert r.status_code == 503
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"].endswith("/dependency-unavailable")
    assert body["errors"] == [{"component": "redis", "msg": "unreachable"}]
