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
    key: PiiMappingKey
    mapped_value: str
    created_at: datetime | None = field(default=None)


class PiiMappingRepository(Protocol):
    async def get_many(
        self,
        keys: set[PiiMappingKey],
    ) -> dict[PiiMappingKey, PiiMappingRecord]: ...


class PiiMappingSnapshotRepository(Protocol):
    def iter_snapshot_batches(
        self,
        *,
        batch_size: int,
    ) -> AsyncIterator[dict[PiiMappingKey, PiiMappingRecord]]: ...

    def iter_incremental_batches(
        self,
        *,
        since: datetime,
        batch_size: int,
    ) -> AsyncIterator[dict[PiiMappingKey, PiiMappingRecord]]: ...
