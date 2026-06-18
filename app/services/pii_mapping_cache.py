from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from app.repositories.interfaces.pii_mapping import PiiMappingKey


@dataclass(frozen=True, slots=True)
class _PiiCacheKey:
    pii_type: str
    token: str


class InMemoryPiiMappingCache:
    def __init__(
        self,
        *,
        missing_ttl_seconds: float = 60.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if missing_ttl_seconds <= 0:
            raise ValueError("missing_ttl_seconds must be greater than zero")

        self.missing_ttl_seconds = missing_ttl_seconds
        self._clock = clock
        self._items: dict[_PiiCacheKey, str] = {}
        self._missing_until: dict[_PiiCacheKey, float] = {}

    def get_many(self, keys: set[PiiMappingKey]) -> dict[PiiMappingKey, str]:
        values: dict[PiiMappingKey, str] = {}
        for key in keys:
            value = self._items.get(self._cache_key(key))
            if value is None:
                continue
            values[key] = value
        return values

    def set_many(self, values: dict[PiiMappingKey, str]) -> None:
        for key, value in values.items():
            cache_key = self._cache_key(key)
            self._items[cache_key] = value
            self._missing_until.pop(cache_key, None)

    def keys_to_load(self, keys: set[PiiMappingKey]) -> set[PiiMappingKey]:
        """Return keys that are not covered by the temporary missing-key cache."""
        now = self._clock()
        keys_to_load: set[PiiMappingKey] = set()
        for key in keys:
            cache_key = self._cache_key(key)
            missing_until = self._missing_until.get(cache_key)
            if missing_until is None:
                keys_to_load.add(key)
                continue
            if missing_until <= now:
                self._missing_until.pop(cache_key, None)
                keys_to_load.add(key)
        return keys_to_load

    def mark_missing(self, keys: set[PiiMappingKey]) -> None:
        missing_until = self._clock() + self.missing_ttl_seconds
        for key in keys:
            cache_key = self._cache_key(key)
            if cache_key not in self._items:
                self._missing_until[cache_key] = missing_until

    def clear(self) -> None:
        self._items.clear()
        self._missing_until.clear()

    @property
    def size(self) -> int:
        return len(self._items)

    def _cache_key(self, key: PiiMappingKey) -> _PiiCacheKey:
        return _PiiCacheKey(pii_type=key.pii_type, token=key.token)
