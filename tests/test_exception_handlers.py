from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.exceptions import register_exception_handlers


class Payload(BaseModel):
    name: str


def test_validation_error_response_serializes_bytes_input() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/payload")
    def create_payload(payload: Payload) -> Payload:
        return payload

    response = TestClient(app).post(
        "/payload",
        data=b"username=admin&password=secret",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    error = body["error"]["details"]["errors"][0]
    assert error["field"] == "request"
    assert error["type"] == "model_attributes_type"
    assert isinstance(error["input"], str)
