from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRecord
from app.services.pii_mapping_cache import InMemoryPiiMappingCache
from app.services.pii_mapping_snapshot import load_pii_mapping_snapshot


class FakeSnapshotRepository:
    def __init__(
        self,
        records: list[PiiMappingRecord],
    ) -> None:
        self.records = records

    async def get_mappings_batch(
        self,
        *,
        limit: int,
        offset: int,
        since: Any = None,
    ) -> list[PiiMappingRecord]:
        return self.records[offset : offset + limit]


@pytest.mark.asyncio
async def test_snapshot_replaces_cache_and_loads_each_batch() -> None:
    old_key = PiiMappingKey("customer_id", "old")
    first_key = PiiMappingKey("customer_id", "customer-1")
    second_key = PiiMappingKey("customer_id", "customer-2")
    cache = InMemoryPiiMappingCache()
    cache.set_many([PiiMappingRecord(pii_type="customer_id", token="old", mapped_value="old-uuid")])
    repository = FakeSnapshotRepository(
        [
            PiiMappingRecord(pii_type="customer_id", token="customer-1", mapped_value="uuid-1"),
            PiiMappingRecord(pii_type="customer_id", token="customer-2", mapped_value="uuid-2"),
        ]
    )

    loaded = await load_pii_mapping_snapshot(
        repository=repository,
        cache=cache,
        batch_size=2,
    )

    assert loaded == 2
    assert cache.get_many({old_key}) == {}
    assert cache.get_many({first_key, second_key}) == {
        first_key: "uuid-1",
        second_key: "uuid-2",
    }


def test_mapping_cache_separates_pii_types() -> None:
    customer_key = PiiMappingKey("customer_id", "shared-token")
    phone_key = PiiMappingKey("phone", "shared-token")
    cache = InMemoryPiiMappingCache()

    cache.set_many([PiiMappingRecord(pii_type="customer_id", token="shared-token", mapped_value="uuid-1")])

    assert cache.get_many({customer_key, phone_key}) == {customer_key: "uuid-1"}
    assert cache.size == 1
