from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.sql import Executable

PiiTokenMapper = Callable[[Any], tuple[str, str] | None]


def default_pii_token_mapper(value: Any) -> tuple[str, str] | None:
    token = str(value)
    if len(token) == 32:
        return token, ""
    elif len(token) == 33:
        return token[:32], token[32]
    return None


def pii_token_when_length_greater_than(
    min_length: int,
    *,
    strip_last_character: bool = False,
) -> PiiTokenMapper:
    def map_token(value: Any) -> tuple[str, str] | None:
        token = str(value)
        if len(token) <= min_length:
            return None
        if strip_last_character:
            return token[:-1], token[-1]
        return token, ""

    return map_token


@dataclass(frozen=True, slots=True)
class PiiFieldMappingRule:
    pii_type: str
    token_mapper: PiiTokenMapper = default_pii_token_mapper


@dataclass(frozen=True, slots=True)
class DataRouteSpec:
    route_name: str
    statement: str | Executable
    pii_field_rules: Mapping[str, str | PiiFieldMappingRule] = field(default_factory=dict)

    @property
    def effective_pii_fields(self) -> tuple[str, ...]:
        return tuple(self.pii_field_rules.keys())

    def get_pii_rule(self, field_name: str) -> PiiFieldMappingRule | None:
        """Return the resolved PiiFieldMappingRule for a field.

        Accepts shorthand string values (treated as pii_type) or full
        PiiFieldMappingRule instances.
        """
        rule = self.pii_field_rules.get(field_name)
        if rule is None:
            return None
        if isinstance(rule, str):
            return PiiFieldMappingRule(pii_type=rule)
        return rule
