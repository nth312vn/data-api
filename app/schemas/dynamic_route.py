from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateDynamicRouteRequest(BaseModel):
    """Request body to create a new dynamic API route."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ..., description="URL path for the route, e.g. '/report/daily_sales'"
    )
    sql: str = Field(
        ...,
        description="SQL query to execute. Use {param} for path param placeholders.",
    )
    path_params: list[str] = Field(
        default_factory=list, description="Names of URL path parameters"
    )
    pii_columns: list[str] = Field(
        default_factory=list,
        description="Column names that require PII transformation",
    )
    description: str = Field(default="", description="Description of this route")
    lab_test: bool = Field(
        default=False, description="If True, execute SQL immediately as a lab test"
    )
    lab_test_params: dict[str, str] = Field(
        default_factory=dict,
        description="Parameter values for lab test execution",
    )


class DynamicRouteResponse(BaseModel):
    """Response for a created dynamic route."""

    path: str
    sql: str
    path_params: list[str]
    pii_columns: list[str]
    description: str
    created_at: datetime
    lab_test_result: list[dict[str, Any]] | None = None


class DynamicRouteListResponse(BaseModel):
    """Response listing all dynamic routes."""

    routes: list[DynamicRouteResponse]
    total: int
