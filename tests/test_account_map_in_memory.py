from typing import Any

import pytest

from app.repositories.interfaces.pii_mapping import PiiMappingRecord
from app.services.account_map_in_memory import AccountMapInMemory
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
async def test_snapshot_replaces_account_map_in_memory() -> None:
    account_map = AccountMapInMemory()
    account_map.add_records([PiiMappingRecord(token="old", mapped_value="old-uuid")])
    repository = FakeSnapshotRepository(
        [
            PiiMappingRecord(token="customer-1", mapped_value="uuid-1"),
            PiiMappingRecord(token="customer-2", mapped_value="uuid-2"),
        ]
    )

    loaded = await load_pii_mapping_snapshot(
        repository=repository,
        cache=account_map,
        batch_size=2,
    )

    assert loaded == 2
    assert account_map.token_to_value == {
        "customer-1": "uuid-1",
        "customer-2": "uuid-2",
    }


def test_account_map_in_memory_uses_plain_key_value_hashmaps() -> None:
    account_map = AccountMapInMemory()

    account_map.add_records(
        [PiiMappingRecord(token="shared-token", mapped_value="uuid-1")]
    )

    assert account_map.token_to_value == {"shared-token": "uuid-1"}
    assert account_map.value_to_token == {"uuid-1": "shared-token"}
