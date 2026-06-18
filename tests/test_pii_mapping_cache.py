from collections.abc import AsyncIterator

import pytest

from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRecord
from app.services.pii_mapping_cache import InMemoryPiiMappingCache
from app.services.pii_mapping_snapshot import load_pii_mapping_snapshot


def test_missing_keys_are_loadable_again_after_ttl() -> None:
    now = [100.0]
    key = PiiMappingKey("trino", "customer_id", "missing")
    cache = InMemoryPiiMappingCache(
        missing_ttl_seconds=30,
        clock=lambda: now[0],
    )

    cache.mark_missing({key})

    assert cache.keys_to_load({key}) == set()
    now[0] = 130.0
    assert cache.keys_to_load({key}) == {key}


def test_value_update_removes_key_from_missing_cache() -> None:
    key = PiiMappingKey("trino", "customer_id", "customer-1")
    cache = InMemoryPiiMappingCache()
    cache.mark_missing({key})

    cache.set_many({key: "uuid-1"})

    assert cache.get_many({key}) == {key: "uuid-1"}
    assert cache.keys_to_load({key}) == {key}


class FakeSnapshotRepository:
    def __init__(
        self,
        batches: list[dict[PiiMappingKey, PiiMappingRecord]],
    ) -> None:
        self.batches = batches
        self.batch_size: int | None = None

    async def iter_snapshot_batches(
        self,
        *,
        batch_size: int,
    ) -> AsyncIterator[dict[PiiMappingKey, PiiMappingRecord]]:
        self.batch_size = batch_size
        for batch in self.batches:
            yield batch


@pytest.mark.asyncio
async def test_snapshot_replaces_cache_and_loads_each_batch() -> None:
    old_key = PiiMappingKey("trino", "customer_id", "old")
    first_key = PiiMappingKey("trino", "customer_id", "customer-1")
    second_key = PiiMappingKey("trino", "customer_id", "customer-2")
    cache = InMemoryPiiMappingCache()
    cache.set_many({old_key: "old-uuid"})
    repository = FakeSnapshotRepository(
        [
            {
                first_key: PiiMappingRecord(first_key, "uuid-1"),
                second_key: PiiMappingRecord(second_key, "uuid-2"),
            }
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
    assert repository.batch_size == 2


def test_mapping_cache_is_shared_across_source_systems() -> None:
    trino_key = PiiMappingKey("trino", "customer_id", "customer-1")
    crm_key = PiiMappingKey("crm", "customer_id", "customer-1")
    cache = InMemoryPiiMappingCache()

    cache.set_many({trino_key: "uuid-1"})

    assert cache.get_many({crm_key}) == {crm_key: "uuid-1"}
    assert cache.size == 1


def test_missing_key_cache_is_shared_across_source_systems() -> None:
    trino_key = PiiMappingKey("trino", "customer_id", "missing")
    crm_key = PiiMappingKey("crm", "customer_id", "missing")
    cache = InMemoryPiiMappingCache()

    cache.mark_missing({trino_key})

    assert cache.keys_to_load({crm_key}) == set()
