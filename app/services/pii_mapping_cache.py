from collections import OrderedDict

from app.repositories.interfaces.pii_mapping import PiiMappingKey


class InMemoryPiiMappingCache:
    def __init__(self, *, max_size: int) -> None:
        self.max_size = max_size
        self._items: OrderedDict[PiiMappingKey, str] = OrderedDict()

    def get_many(self, keys: set[PiiMappingKey]) -> dict[PiiMappingKey, str]:
        values: dict[PiiMappingKey, str] = {}
        for key in keys:
            value = self._items.get(key)
            if value is None:
                continue
            self._items.move_to_end(key)
            values[key] = value
        return values

    def set_many(self, values: dict[PiiMappingKey, str]) -> None:
        for key, value in values.items():
            self._items[key] = value
            self._items.move_to_end(key)

        while len(self._items) > self.max_size:
            self._items.popitem(last=False)
