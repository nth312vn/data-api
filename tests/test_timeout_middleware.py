import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middlewares.request_id import RequestIDMiddleware
from app.middlewares.timeout import RequestTimeoutMiddleware


def test_request_timeout_returns_gateway_timeout_with_request_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=0.01)
    app.add_middleware(RequestIDMiddleware)

    @app.get("/slow")
    async def slow() -> dict[str, bool]:
        await asyncio.sleep(0.05)
        return {"ok": True}

    response = TestClient(app).get(
        "/slow",
        headers={"X-Request-ID": "req-timeout"},
    )

    assert response.status_code == 504
    assert response.headers["X-Request-ID"] == "req-timeout"
    assert response.json() == {
        "error": {
            "code": "request_timeout",
            "message": "Request timed out",
            "details": {"timeout_seconds": 0.01},
            "request_id": "req-timeout",
        },
    }
