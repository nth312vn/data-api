import httpx
from fastapi.testclient import TestClient

from app.core.metrics import start_metrics_server, stop_metrics_server
from app.main import create_app


def test_metrics_are_exposed_on_separate_prometheus_port() -> None:
    app = create_app()
    client = TestClient(app)

    client.get("/missing")

    metrics_server = start_metrics_server(host="127.0.0.1", port=0)
    try:
        server, _ = metrics_server
        response = httpx.get(f"http://127.0.0.1:{server.server_port}/metrics")
    finally:
        stop_metrics_server(metrics_server)

    assert response.headers["content-type"].startswith("text/plain")
    assert "data_api_http_requests_total" in response.text
    assert 'method="GET"' in response.text
    assert 'path="/missing"' in response.text
    assert 'status_code="404"' in response.text
    assert client.get("/metrics").status_code == 404
