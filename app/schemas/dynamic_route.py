from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.models.dynamic_route import (
    DynamicRouteDatabaseType,
    DynamicRoutePiiType,
    DynamicRouteResponseType,
)
from app.services.query_engine.dynamic_parameters import (
    DynamicParameterDefinition,
)

_PREFIX = re.compile(r"[a-zA-Z0-9_.-]+\Z")
_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_RESERVED_PREFIXES = frozenset({"dynamic-routes"})
_PAGINATION_PARAMETERS = frozenset(
    {"page", "page_size", "__dynamic_page_size", "__dynamic_offset"}
)


class DynamicRouteWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix: str = Field(min_length=3, max_length=50)
    path: str = Field(min_length=1, max_length=500)
    sql: str = Field(min_length=1)
    params: dict[str, DynamicParameterDefinition] = Field(default_factory=dict)
    description: str = ""
    db_type: DynamicRouteDatabaseType = DynamicRouteDatabaseType.trino
    pii_type: DynamicRoutePiiType | None = None
    response_type: DynamicRouteResponseType = DynamicRouteResponseType.data
    lab_test: bool = False
    lab_test_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prefix", mode="before")
    @classmethod
    def normalize_prefix(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        if not _PREFIX.fullmatch(value):
            raise ValueError("prefix contains unsupported characters")
        if value in _RESERVED_PREFIXES:
            raise ValueError("prefix is reserved")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("path cannot start or end with whitespace")
        if value.startswith("/") or value.endswith("/"):
            raise ValueError("path must be relative")
        segments = value.split("/")
        if any(not segment or segment in {".", ".."} for segment in segments):
            raise ValueError("path contains an invalid segment")
        return value

    @field_validator("params")
    @classmethod
    def validate_parameter_names(
        cls,
        value: dict[str, DynamicParameterDefinition],
    ) -> dict[str, DynamicParameterDefinition]:
        if any(not _PARAMETER_NAME.fullmatch(name) for name in value):
            raise ValueError("parameter names must be ASCII identifiers")
        return value

    @model_validator(mode="after")
    def validate_paginated_parameter_names(self) -> DynamicRouteWriteRequest:
        if self.response_type is DynamicRouteResponseType.paginated:
            reserved = sorted(_PAGINATION_PARAMETERS & self.params.keys())
            if reserved:
                raise ValueError(
                    "paginated route uses a reserved pagination parameter"
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def api_path(self) -> str:
        return f"/{self.prefix}/{self.path}"


class DynamicRouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prefix: str
    path: str
    description: str
    sql: str
    canonical_sql: str
    params: dict[str, DynamicParameterDefinition]
    db_type: DynamicRouteDatabaseType
    pii_type: DynamicRoutePiiType | None
    response_type: DynamicRouteResponseType
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def api_path(self) -> str:
        return f"/{self.prefix}/{self.path}"


class DynamicRouteListResponse(BaseModel):
    routes: list[DynamicRouteResponse]
    total: int
