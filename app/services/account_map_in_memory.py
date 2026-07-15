from collections.abc import Iterable
from datetime import datetime

from app.repositories.interfaces.pii_mapping import PiiMappingRecord


class AccountMapInMemory:
    def __init__(self) -> None:
        self.hashmap_token_to_value: dict[str, str] = {}
        self.hashmap_value_to_token: dict[str, str] = {}
        self._last_synced_at: datetime | None = None

    @property
    def last_synced_at(self) -> datetime | None:
        """Max created_at of records loaded into memory."""
        return self._last_synced_at

    def _update_last_synced_at(self, value: datetime) -> None:
        """Advance last_synced_at to value if value is newer."""
        if self._last_synced_at is None or value > self._last_synced_at:
            self._last_synced_at = value

    @property
    def token_to_value(self) -> dict[str, str]:
        return self.hashmap_token_to_value

    @property
    def value_to_token(self) -> dict[str, str]:
        return self.hashmap_value_to_token

    def add_record(self, record: PiiMappingRecord) -> None:
        self.hashmap_token_to_value[record.token] = record.mapped_value
        self.hashmap_value_to_token[record.mapped_value] = record.token

        if record.created_at is not None:
            self._update_last_synced_at(record.created_at)

    def add_records(self, records: Iterable[PiiMappingRecord]) -> None:
        for record in records:
            self.add_record(record)

    def clear(self) -> None:
        self.hashmap_token_to_value.clear()
        self.hashmap_value_to_token.clear()
        self._last_synced_at = None

    @property
    def size(self) -> int:
        return len(self.hashmap_token_to_value)
