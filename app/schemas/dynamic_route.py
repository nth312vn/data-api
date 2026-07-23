from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SqlParamSpecSchema(BaseModel):
    """Specification for a dynamic SQL parameter."""

    type: Literal["string", "date", "integer", "float", "boolean", "string_list"] = Field(
        ..., description="Type of parameter"
    )
    required: bool = Field(default=True, description="Whether the parameter is required")
    default: str | None = Field(default=None, description="Default value if not provided")
    description: str = Field(default="", description="Description of the parameter")


class PiiTransformRuleSchema(BaseModel):
    """Custom parameterized PII transformation rule details."""

    when_length: int | None = Field(default=None, description="Only apply when length matches")
    when_min_length: int | None = Field(default=None, description="Only apply when length exceeds min")
    token_slice: list[int | None] | None = Field(default=None, description="[start, end] slice for token")
    suffix_slice: list[int | None] | None = Field(default=None, description="[start, end] slice for suffix")
    strip_last_as_suffix: bool = Field(default=False, description="Whether to treat the last character as suffix")


class PiiColumnRuleSchema(BaseModel):
    """PII transformation rule configuration for a column."""

    preset: str | None = Field(default=None, description="Preset rule name, e.g. token_length")
    custom_rules: list[PiiTransformRuleSchema] | None = Field(
        default=None, description="List of custom PII mapping rules"
    )


class CreateDynamicRouteRequest(BaseModel):
    """Request body to create a new dynamic API route."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ..., description="URL path for the route, e.g. '/report/daily_sales'"
    )
    sql: str = Field(
        ...,
        description="SQL query to execute. Use :param for parameterized placeholders.",
    )
    params: dict[str, SqlParamSpecSchema] = Field(
        default_factory=dict, description="Names and specifications of SQL parameters"
    )
    pii_rules: dict[str, PiiColumnRuleSchema] = Field(
        default_factory=dict,
        description="Column names and their PII transformation rules",
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
    params: dict[str, SqlParamSpecSchema]
    pii_rules: dict[str, PiiColumnRuleSchema]
    description: str
    created_at: datetime
    lab_test_result: list[dict[str, Any]] | None = None


class DynamicRouteListResponse(BaseModel):
    """Response listing all dynamic routes."""

    routes: list[DynamicRouteResponse]
    total: int
