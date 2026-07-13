from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PiiMappingKey:
    pii_type: str
    token: str


@dataclass(frozen=True, slots=True)
class PiiMappingRecord:
    pii_type: str
    token: str
    mapped_value: str
    created_at: datetime | None = None


class PiiMappingRepository(Protocol):
    async def get_many(
        self,
        keys: set[PiiMappingKey],
    ) -> dict[PiiMappingKey, PiiMappingRecord]: ...


class PiiMappingSnapshotRepository(Protocol):
    async def get_mappings_batch(
        self,
        *,
        limit: int,
        offset: int,
        since: datetime | None = None,
    ) -> list[PiiMappingRecord]: ...
