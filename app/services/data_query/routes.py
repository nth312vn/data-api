from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.sql import Executable

PiiTokenMapper = Callable[[Any], str | None]


def default_pii_token_mapper(value: Any) -> str:
    return str(value)


def pii_token_when_length_greater_than(
    min_length: int,
    *,
    strip_last_character: bool = False,
) -> PiiTokenMapper:
    def map_token(value: Any) -> str | None:
        token = str(value)
        if len(token) <= min_length:
            return None
        if strip_last_character:
            return token[:-1]
        return token

    return map_token


@dataclass(frozen=True, slots=True)
class PiiFieldMappingRule:
    pii_type: str
    token_mapper: PiiTokenMapper = default_pii_token_mapper


@dataclass(frozen=True, slots=True)
class DataRouteSpec:
    route_name: str
    statement: str | Executable
    pii_fields: tuple[str, ...]
    pii_field_rules: Mapping[str, PiiFieldMappingRule] = field(default_factory=dict)
