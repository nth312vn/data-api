from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.dynamic_route import (
    DynamicRouteDatabaseType,
    DynamicRoutePiiType,
    DynamicRouteResponseType,
)
from app.schemas.dynamic_route import (
    DynamicRouteResponse,
    DynamicRouteWriteRequest,
)


def test_dynamic_route_write_schema_normalizes_prefix_and_computes_path() -> None:
    request = DynamicRouteWriteRequest(
        prefix=" Power_BI ",
        path="customer-sales",
        sql="SELECT * FROM sales WHERE region = :region",
        params={"region": {"type": "string", "required": True}},
    )

    assert request.prefix == "power_bi"
    assert request.api_path == "/power_bi/customer-sales"
    assert request.db_type is DynamicRouteDatabaseType.trino
    assert request.pii_type is None
    assert request.response_type is DynamicRouteResponseType.data


@pytest.mark.parametrize(
    ("prefix", "path"),
    [
        ("dynamic-routes", "report"),
        ("ab", "report"),
        ("Power BI", "report"),
        ("power_bi", ""),
        ("power_bi", "/report"),
        ("power_bi", "report/"),
        ("power_bi", "report//daily"),
        ("power_bi", "report/./daily"),
        ("power_bi", "report/../daily"),
    ],
)
def test_dynamic_route_write_schema_rejects_reserved_or_invalid_paths(
    prefix: str,
    path: str,
) -> None:
    with pytest.raises(ValidationError):
        DynamicRouteWriteRequest(
            prefix=prefix,
            path=path,
            sql="SELECT 1",
        )


def test_dynamic_route_write_schema_rejects_removed_or_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DynamicRouteWriteRequest(
            prefix="power_bi",
            path="customer",
            sql="SELECT 1",
            path_params=["region"],
            pii_columns=["customer_id"],
        )


def test_dynamic_route_response_exposes_execution_types() -> None:
    response = DynamicRouteResponse(
        id=uuid4(),
        prefix="power_bi",
        path="customer",
        description="Customer report",
        sql="SELECT customer_id FROM customer",
        canonical_sql="SELECT customer_id FROM customer",
        params={},
        db_type="postgres",
        pii_type="customer_id",
        response_type="paginated",
        created_by=None,
        updated_by=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert response.api_path == "/power_bi/customer"
    assert response.db_type is DynamicRouteDatabaseType.postgres
    assert response.pii_type is DynamicRoutePiiType.customer_id
    assert response.response_type is DynamicRouteResponseType.paginated
    assert "lab_test_result" not in DynamicRouteResponse.model_fields


def test_paginated_route_reserves_pagination_parameters() -> None:
    with pytest.raises(ValidationError):
        DynamicRouteWriteRequest(
            prefix="power_bi",
            path="customer",
            sql="SELECT :page",
            params={"page": {"type": "integer"}},
            response_type="paginated",
        )
