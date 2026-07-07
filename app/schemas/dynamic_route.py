from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateDynamicRouteRequest(BaseModel):
    """Request body to create a new dynamic API route."""
    path: str = Field(..., description="URL path for the route, e.g. '/report/daily_sales'")
    sql: str = Field(..., description="SQL query to execute. Use {param} for path param placeholders.")
    path_params: list[str] = Field(default_factory=list, description="Names of URL path parameters")
    pii_rules: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of column_name -> pii_category for PII transformation",
    )
    description: str = Field(default="", description="Description of this route")
    lab_test: bool = Field(default=False, description="If True, execute SQL immediately as a lab test")
    lab_test_params: dict[str, str] = Field(
        default_factory=dict,
        description="Parameter values for lab test execution",
    )


class DynamicRouteResponse(BaseModel):
    """Response for a created dynamic route."""
    path: str
    sql: str
    path_params: list[str]
    pii_rules: dict[str, str]
    description: str
    created_at: datetime
    lab_test_result: list[dict[str, Any]] | None = None


class DynamicRouteListResponse(BaseModel):
    """Response listing all dynamic routes."""
    routes: list[DynamicRouteResponse]
    total: int
