from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PiiMappingKey:
    source_system: str
    pii_type: str
    token: str


@dataclass(frozen=True, slots=True)
class PiiMappingRecord:
    key: PiiMappingKey
    mapped_value: str


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
