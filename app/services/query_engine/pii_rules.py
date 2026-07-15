from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.sql import Executable


class PiiValueTransformer(Protocol):
    def __call__(
        self,
        value: Any,
        pii_cache: Mapping[str, str],
    ) -> Any: ...


def transform_by_token_length(
    value: Any,
    pii_cache: Mapping[str, str],
) -> Any:
    """Transform value with the 32/33-character token rule.

    - Length 32: token = value, no suffix.
    - Length 33: token = value[:32], suffix = value[32].
    - Missing or invalid token: return None so the response column becomes null.
    """
    if value is None:
        return None
    token = str(value)
    if len(token) == 32:
        return pii_cache.get(token)
    if len(token) == 33:
        mapped = pii_cache.get(token[:32])
        if mapped is not None:
            return mapped + token[32]
        return None
    return None


def transform_when_exceeds_length(
    value: Any,
    pii_cache: Mapping[str, str],
    *,
    min_length: int,
    strip_last_character: bool = False,
) -> Any:
    """Transform value when its length exceeds min_length.

    min_length and strip_last_character are options bound with partial:
        PiiColumnRule(
            transformer=partial(transform_when_exceeds_length, min_length=10),
        )
    """
    if value is None:
        return None
    token = str(value)
    if len(token) <= min_length:
        return None
    if strip_last_character:
        actual_token, suffix = token[:-1], token[-1]
    else:
        actual_token, suffix = token, ""

    mapped = pii_cache.get(actual_token)
    if mapped is not None:
        return mapped + suffix
    return None


@dataclass(frozen=True, slots=True)
class PiiColumnRule:
    """Rule áp dụng cho 1 column để transform giá trị PII.

    transformer: Hàm transform — BẮT BUỘC phải define, không có default.
    """

    transformer: PiiValueTransformer = field(repr=False)


@dataclass(frozen=True, slots=True)
class QuerySpec:
    """Spec mô tả 1 query kèm PII rules cho từng column.

    route_name: Tên định danh cho route (dùng cho audit log).
    statement: SQL query string hoặc SQLAlchemy Executable.
    column_pii_rules: Mapping column_name -> PiiColumnRule.
    """

    route_name: str
    statement: str | Executable
    column_pii_rules: Mapping[str, PiiColumnRule] = field(default_factory=dict)

    @property
    def pii_columns(self) -> tuple[str, ...]:
        """Danh sách tên columns có PII rule."""
        return tuple(self.column_pii_rules.keys())

    def get_pii_rule(self, column_name: str) -> PiiColumnRule | None:
        """Return PiiColumnRule cho column, hoặc None nếu không có."""
        return self.column_pii_rules.get(column_name)
