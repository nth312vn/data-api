from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from fastapi import status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    TextClause,
    bindparam,
    text,
)
from starlette.datastructures import QueryParams

from app.core.exceptions import AppError

_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")


class DynamicParameterError(AppError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=code,
            message=message,
            details=details,
        )


class DynamicParameterType(StrEnum):
    string = "string"
    integer = "integer"
    float = "float"
    boolean = "boolean"
    date = "date"
    datetime = "datetime"
    string_list = "string_list"


ParameterDefault = str | int | float | bool | date | datetime | list[str] | None


class DynamicParameterDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: DynamicParameterType
    required: bool = True
    default: ParameterDefault = None
    description: str = ""

    @model_validator(mode="after")
    def validate_default(self) -> DynamicParameterDefinition:
        if self.required and self.default is not None:
            raise ValueError("required parameters cannot define a default")
        if not self.required and self.default is not None:
            try:
                _cast_value(self.type, self.default)
            except DynamicParameterError as exc:
                raise ValueError("default does not match parameter type") from exc
        return self


def validate_parameter_contract(
    parameter_names: frozenset[str],
    definitions: Mapping[str, DynamicParameterDefinition],
) -> None:
    invalid_names = sorted(
        name for name in definitions if not _PARAMETER_NAME.fullmatch(name)
    )
    if invalid_names:
        raise DynamicParameterError(
            "dynamic_parameter_invalid_name",
            "Parameter names must be ASCII identifiers",
            details={"invalid_names": invalid_names},
        )

    definition_names = set(definitions)
    missing = sorted(parameter_names - definition_names)
    unused = sorted(definition_names - parameter_names)
    if missing or unused:
        raise DynamicParameterError(
            "dynamic_parameter_contract_mismatch",
            "SQL placeholders and parameter definitions must match exactly",
            details={
                "missing_definitions": missing,
                "unused_definitions": unused,
            },
        )


def cast_parameter_values(
    definitions: Mapping[str, DynamicParameterDefinition],
    raw_values: QueryParams | Mapping[str, object],
) -> dict[str, object]:
    supplied = _collect_raw_values(raw_values)
    unknown = sorted(set(supplied) - set(definitions))
    if unknown:
        raise DynamicParameterError(
            "dynamic_parameter_unknown",
            "Request contains undeclared parameters",
            details={"parameters": unknown},
        )

    result: dict[str, object] = {}
    for name, definition in definitions.items():
        values = supplied.get(name)
        if values is None:
            if definition.required:
                raise DynamicParameterError(
                    "dynamic_parameter_missing",
                    f"Required parameter '{name}' is missing",
                    details={"parameter": name},
                )
            result[name] = (
                None
                if definition.default is None
                else _cast_value(definition.type, definition.default)
            )
            continue

        if definition.type is DynamicParameterType.string_list:
            result[name] = _cast_string_list(values, name)
            continue
        if len(values) != 1:
            raise DynamicParameterError(
                "dynamic_parameter_invalid",
                f"Parameter '{name}' must be supplied once",
                details={"parameter": name},
            )
        result[name] = _cast_value(definition.type, values[0], name=name)
    return result


def build_bound_statement(
    canonical_sql: str,
    definitions: Mapping[str, DynamicParameterDefinition],
) -> TextClause:
    statement = text(canonical_sql)
    binds = []
    for name, definition in definitions.items():
        if definition.type is DynamicParameterType.string_list:
            binds.append(bindparam(name, expanding=True, type_=String()))
        else:
            binds.append(bindparam(name, type_=_sqlalchemy_type(definition.type)))
    return statement.bindparams(*binds)


def _collect_raw_values(
    raw_values: QueryParams | Mapping[str, object],
) -> dict[str, list[object]]:
    if isinstance(raw_values, QueryParams):
        return {key: list(raw_values.getlist(key)) for key in raw_values}

    collected: dict[str, list[object]] = {}
    for key, value in raw_values.items():
        if isinstance(value, list):
            collected[key] = list(value)
        else:
            collected[key] = [value]
    return collected


def _cast_value(
    parameter_type: DynamicParameterType,
    value: object,
    *,
    name: str = "default",
) -> object:
    try:
        if parameter_type is DynamicParameterType.string:
            if not isinstance(value, str):
                raise ValueError
            return value
        if parameter_type is DynamicParameterType.integer:
            if isinstance(value, bool):
                raise ValueError
            if isinstance(value, int):
                return value
            if isinstance(value, str) and _INTEGER.fullmatch(value):
                return int(value)
            raise ValueError
        if parameter_type is DynamicParameterType.float:
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError
            converted = float(value)
            if not math.isfinite(converted):
                raise ValueError
            return converted
        if parameter_type is DynamicParameterType.boolean:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.casefold()
                if normalized in {"true", "1"}:
                    return True
                if normalized in {"false", "0"}:
                    return False
            raise ValueError
        if parameter_type is DynamicParameterType.date:
            if isinstance(value, datetime):
                raise ValueError
            if isinstance(value, date):
                return value
            if isinstance(value, str):
                return date.fromisoformat(value)
            raise ValueError
        if parameter_type is DynamicParameterType.datetime:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value)
            raise ValueError
        if parameter_type is DynamicParameterType.string_list:
            if not isinstance(value, list):
                raise ValueError
            return _cast_string_list(list(value), name)
    except (TypeError, ValueError) as exc:
        raise DynamicParameterError(
            "dynamic_parameter_invalid",
            f"Parameter '{name}' is not a valid {parameter_type.value}",
            details={"parameter": name, "expected_type": parameter_type.value},
        ) from exc

    raise DynamicParameterError(
        "dynamic_parameter_invalid",
        f"Unsupported parameter type for '{name}'",
        details={"parameter": name},
    )


def _cast_string_list(values: list[object], name: str) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise DynamicParameterError(
                "dynamic_parameter_invalid",
                f"Parameter '{name}' must contain only strings",
                details={"parameter": name},
            )
        result.extend(part.strip() for part in value.split(","))
    if not result or any(not item for item in result):
        raise DynamicParameterError(
            "dynamic_parameter_invalid",
            f"Parameter '{name}' must contain non-empty strings",
            details={"parameter": name},
        )
    return result


def _sqlalchemy_type(parameter_type: DynamicParameterType) -> Any:
    return {
        DynamicParameterType.string: String(),
        DynamicParameterType.integer: Integer(),
        DynamicParameterType.float: Float(),
        DynamicParameterType.boolean: Boolean(),
        DynamicParameterType.date: Date(),
        DynamicParameterType.datetime: DateTime(timezone=True),
    }[parameter_type]
