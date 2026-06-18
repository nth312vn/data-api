import json

from app.main import app


def test_oauth2_password_flow_uses_form_token_endpoint() -> None:
    schema = app.openapi()

    password_flow = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"][
        "flows"
    ]["password"]

    assert password_flow["tokenUrl"] == "/api/v1/auth/token"
    json.dumps(schema)


def test_removed_role_and_permission_apis_are_not_exposed() -> None:
    paths = app.openapi()["paths"]

    assert not any(path.startswith("/api/v1/roles") for path in paths)
    assert not any(path.startswith("/api/v1/api_permissions") for path in paths)
    assert not any(path.endswith("/roles") for path in paths)
    assert not any("/permissions" in path for path in paths)


def test_user_schema_contains_only_single_role_source() -> None:
    schemas = app.openapi()["components"]["schemas"]
    properties = schemas["UserRead"]["properties"]
    role_values = schemas["UserRole"]["enum"]

    assert "role" in properties
    assert "full_name" not in properties
    assert "is_active" not in properties
    assert role_values == ["user", "admin"]
