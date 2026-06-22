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
        self._next_missing_expiry: float | None = None

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
        self._clear_expired_missing(now)
        keys_to_load: set[PiiMappingKey] = set()
        for key in keys:
            cache_key = self._cache_key(key)
            missing_until = self._missing_until.get(cache_key)
            if missing_until is None:
                keys_to_load.add(key)
        return keys_to_load

    def mark_missing(self, keys: set[PiiMappingKey]) -> None:
        now = self._clock()
        self._clear_expired_missing(now)
        missing_until = now + self.missing_ttl_seconds
        for key in keys:
            cache_key = self._cache_key(key)
            if cache_key not in self._items:
                self._missing_until[cache_key] = missing_until
                if (
                    self._next_missing_expiry is None
                    or missing_until < self._next_missing_expiry
                ):
                    self._next_missing_expiry = missing_until

    def clear(self) -> None:
        self._items.clear()
        self._missing_until.clear()
        self._next_missing_expiry = None

    @property
    def size(self) -> int:
        return len(self._items)

    @property
    def missing_size(self) -> int:
        return len(self._missing_until)

    def _clear_expired_missing(self, now: float) -> None:
        if self._next_missing_expiry is None or self._next_missing_expiry > now:
            return

        self._missing_until = {
            key: missing_until
            for key, missing_until in self._missing_until.items()
            if missing_until > now
        }
        self._next_missing_expiry = min(
            self._missing_until.values(),
            default=None,
        )

    def _cache_key(self, key: PiiMappingKey) -> _PiiCacheKey:
        return _PiiCacheKey(pii_type=key.pii_type, token=key.token)
