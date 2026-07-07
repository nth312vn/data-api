from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.sql import Executable

if TYPE_CHECKING:
    from app.repositories.interfaces.pii_mapping import PiiMappingKey

# Transformer nhận column value, toàn bộ PII cache, và pii_category từ rule.
# min_length / strip_last_character là options của từng hàm — bind qua partial khi define.
PiiValueTransformer = Callable[[Any, "dict[PiiMappingKey, str]", str], Any]


def transform_by_token_length(
    value: Any,
    pii_cache: dict[PiiMappingKey, str],
    pii_category: str,
) -> Any:
    """Transform value dùng quy tắc 32/33 ký tự và lookup pii_cache theo pii_category.

    - Độ dài 32: token = value, không có suffix.
    - Độ dài 33: token = value[:32], suffix = value[32].
    - Không match: giữ nguyên giá trị gốc.
    """
    from app.repositories.interfaces.pii_mapping import PiiMappingKey

    if value is None:
        return value
    token = str(value)
    if len(token) == 32:
        mapped = pii_cache.get(PiiMappingKey(pii_type=pii_category, token=token))
        return mapped if mapped is not None else value
    if len(token) == 33:
        mapped = pii_cache.get(PiiMappingKey(pii_type=pii_category, token=token[:32]))
        return (mapped + token[32]) if mapped is not None else value
    return value


def transform_when_exceeds_length(
    value: Any,
    pii_cache: dict[PiiMappingKey, str],
    pii_category: str,
    *,
    min_length: int,
    strip_last_character: bool = False,
) -> Any:
    """Transform value khi độ dài > min_length, bỏ qua các giá trị ngắn hơn.

    min_length và strip_last_character là options của hàm này — bind qua partial:
        PiiColumnRule(
            pii_category="x",
            transformer=partial(transform_when_exceeds_length, min_length=10),
        )
    """
    from app.repositories.interfaces.pii_mapping import PiiMappingKey

    if value is None:
        return value
    token = str(value)
    if len(token) <= min_length:
        return value
    if strip_last_character:
        actual_token, suffix = token[:-1], token[-1]
    else:
        actual_token, suffix = token, ""
    mapped = pii_cache.get(PiiMappingKey(pii_type=pii_category, token=actual_token))
    return (mapped + suffix) if mapped is not None else value


@dataclass(frozen=True, slots=True)
class PiiColumnRule:
    """Rule áp dụng cho 1 column để transform giá trị PII.

    pii_category: Loại PII (vd: "customer_id", "accountid").
    transformer: Hàm transform — BẮT BUỘC phải define, không có default.
    """

    pii_category: str
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
