from dataclasses import dataclass
from datetime import datetime

from collections.abc import Iterable

from app.repositories.interfaces.pii_mapping import PiiMappingKey, PiiMappingRecord


class InMemoryPiiMappingCache:
    def __init__(self) -> None:
        self.token_to_value: dict[tuple[str, str], str] = {}
        self.value_to_token: dict[tuple[str, str], str] = {}
        self._last_synced_at: datetime | None = None

    @property
    def last_synced_at(self) -> datetime | None:
        """Max created_at of records loaded into cache. None if cache not yet initialized."""
        return self._last_synced_at

    def _update_last_synced_at(self, value: datetime) -> None:
        """Advance last_synced_at to value if value is newer."""
        if self._last_synced_at is None or value > self._last_synced_at:
            self._last_synced_at = value

    def get_many(self, keys: set[PiiMappingKey]) -> dict[PiiMappingKey, str]:
        values: dict[PiiMappingKey, str] = {}
        for key in keys:
            value = self.token_to_value.get((key.pii_type, key.token))
            if value is None:
                continue
            values[key] = value
        return values

    def set_many(self, records: Iterable[PiiMappingRecord]) -> None:
        for record in records:
            cache_key = (record.pii_type, record.token)
            value_key = (record.pii_type, record.mapped_value)
            
            self.token_to_value[cache_key] = record.mapped_value
            self.value_to_token[value_key] = record.token
            
            if record.created_at is not None:
                self._update_last_synced_at(record.created_at)

    def clear(self) -> None:
        self.token_to_value.clear()
        self.value_to_token.clear()
        self._last_synced_at = None

    @property
    def size(self) -> int:
        return len(self.token_to_value)
