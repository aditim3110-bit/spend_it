import httpx


async def test_unknown_route_is_problem_json(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"
    assert body["type"].endswith("/not-found")


async def test_wrong_method_is_problem_json(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/health")
    assert r.status_code == 405
    assert r.headers["content-type"] == "application/problem+json"
