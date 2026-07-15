import pytest
from pydantic import ValidationError

from app.schemas.dynamic_route import CreateDynamicRouteRequest, DynamicRouteResponse


def test_dynamic_route_schema_declares_pii_columns_without_categories() -> None:
    request = CreateDynamicRouteRequest(
        path="/report/customer",
        sql="SELECT customer_id FROM customer",
        pii_columns=["customer_id"],
    )

    assert request.pii_columns == ["customer_id"]
    assert "pii_rules" not in CreateDynamicRouteRequest.model_fields
    assert "pii_rules" not in DynamicRouteResponse.model_fields


def test_dynamic_route_schema_rejects_legacy_pii_rules() -> None:
    with pytest.raises(ValidationError, match="pii_rules"):
        CreateDynamicRouteRequest(
            path="/report/customer",
            sql="SELECT customer_id FROM customer",
            pii_rules={"customer_id": "customer_id"},
        )
