import pytest
from pydantic import ValidationError

from app.schemas.dynamic_route import CreateDynamicRouteRequest, PiiColumnRuleSchema, SqlParamSpecSchema


def test_dynamic_route_schema_declares_params_and_pii_rules() -> None:
    request = CreateDynamicRouteRequest(
        path="/report/customer",
        sql="SELECT customer_id FROM customer WHERE id = :id",
        params={
            "id": SqlParamSpecSchema(type="integer")
        },
        pii_rules={
            "customer_id": PiiColumnRuleSchema(preset="token_length")
        },
    )

    assert "id" in request.params
    assert request.params["id"].type == "integer"
    assert "customer_id" in request.pii_rules
    assert request.pii_rules["customer_id"].preset == "token_length"


def test_dynamic_route_schema_rejects_invalid_param_type() -> None:
    with pytest.raises(ValidationError):
        CreateDynamicRouteRequest(
            path="/report/customer",
            sql="SELECT customer_id FROM customer",
            params={
                "id": {"type": "invalid_type"}  # type: ignore
            }
        )
