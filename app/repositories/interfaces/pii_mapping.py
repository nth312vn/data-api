from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PiiMappingRecord:
    token: str
    mapped_value: str
    created_at: datetime | None = None


class PiiMappingRepository(Protocol):
    async def get_many(
        self,
        *,
        tokens: set[str],
    ) -> dict[str, PiiMappingRecord]: ...


class PiiMappingSnapshotRepository(Protocol):
    async def get_mappings_batch(
        self,
        *,
        limit: int,
        offset: int,
        since: datetime | None = None,
    ) -> list[PiiMappingRecord]: ...
