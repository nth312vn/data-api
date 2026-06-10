import json

from app.main import app


def test_oauth2_password_flow_uses_form_token_endpoint() -> None:
    schema = app.openapi()

    password_flow = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"][
        "flows"
    ]["password"]

    assert password_flow["tokenUrl"] == "/api/v1/auth/token"
    json.dumps(schema)
