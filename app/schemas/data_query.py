from typing import Any

from pydantic import BaseModel


class MissingPiiMapping(BaseModel):
    source_system: str
    pii_type: str
    token: str


class DataRowsResponse(BaseModel):
    rows: list[dict[str, Any]]
    missing_mappings: list[MissingPiiMapping]
