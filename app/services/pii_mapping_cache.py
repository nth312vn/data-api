from dataclasses import dataclass
from datetime import datetime

from collections.abc import Iterable

from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRecord


class InMemoryPiiMappingCache:
    def __init__(self) -> None:
        self.hashmap_token_to_value: dict[tuple[str, str], str] = {}
        self.hashmap_value_to_token: dict[tuple[str, str], str] = {}
        self._last_synced_at: datetime | None = None

    @property
    def last_synced_at(self) -> datetime | None:
        """Max created_at of records loaded into cache. None if cache not yet initialized."""
        return self._last_synced_at

    def _update_last_synced_at(self, value: datetime) -> None:
        """Advance last_synced_at to value if value is newer."""
        if self._last_synced_at is None or value > self._last_synced_at:
            self._last_synced_at = value

    def get_hashmap_token_to_value(self) -> dict[tuple[str, str], str]:
        return self.hashmap_token_to_value

    def get_hashmap_value_to_token(self) -> dict[tuple[str, str], str]:
        return self.hashmap_value_to_token

    def add_records(self, records: Iterable[PiiMappingRecord]) -> None:
        for record in records:
            cache_key = (record.pii_type, record.token)
            value_key = (record.pii_type, record.mapped_value)
            
            self.hashmap_token_to_value[cache_key] = record.mapped_value
            self.hashmap_value_to_token[value_key] = record.token
            
            if record.created_at is not None:
                self._update_last_synced_at(record.created_at)

    def clear(self) -> None:
        self.hashmap_token_to_value.clear()
        self.hashmap_value_to_token.clear()
        self._last_synced_at = None

    @property
    def size(self) -> int:
        return len(self.hashmap_token_to_value)
