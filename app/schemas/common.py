from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class HealthCheck(BaseModel):
    status: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object] | list[object]
    request_id: str | None = None


class MissingPiiMapping(BaseModel):
    pii_type: str
    token: str


class DataRowsResponse(BaseModel):
    rows: list[dict[str, Any]]
    missing_mappings: list[MissingPiiMapping] = Field(default_factory=list)


class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    pagination: PaginationMeta
    missing_mappings: list[MissingPiiMapping] = Field(default_factory=list)


class SuccessResponse(BaseModel):
    message: str = "OK"
    data: Any = None
