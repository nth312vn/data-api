from typing import Any

from pydantic import BaseModel


class MissingPiiMapping(BaseModel):
    pii_type: str
    token: str


class DataRowsResponse(BaseModel):
    rows: list[dict[str, Any]]
    missing_mappings: list[MissingPiiMapping]
