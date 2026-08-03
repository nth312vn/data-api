from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import cast

import sqlglot
from fastapi import status
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError, SqlglotError

from app.core.exceptions import AppError

_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ALLOWED_CONTROL_CHARACTERS = frozenset({"\t", "\n", "\r"})
_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Revoke,
    exp.Set,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Execute,
    exp.Show,
    exp.Describe,
    exp.Command,
)


class DynamicSqlError(AppError):
    """A stable client error raised when dynamic SQL fails the safety policy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=code,
            message=message,
        )


@dataclass(frozen=True, slots=True)
class ValidatedSql:
    canonical_sql: str
    parameter_names: frozenset[str]


class SqlSafetyValidator:
    """Parse dynamic SQL with the selected grammar and allow only one SELECT."""

    def validate(self, sql: str, *, dialect: str = "trino") -> ValidatedSql:
        _validate_characters(sql)
        if not sql.strip():
            raise DynamicSqlError(
                "dynamic_sql_empty",
                "SQL must not be empty",
            )

        try:
            statements = sqlglot.parse(
                sql,
                read=dialect,
                error_level=ErrorLevel.RAISE,
            )
        except ParseError as exc:
            if any(error.get("highlight") == ":" for error in exc.errors):
                raise DynamicSqlError(
                    "dynamic_sql_invalid_parameter",
                    "SQL parameters must use :name with an ASCII identifier",
                ) from exc
            raise DynamicSqlError(
                "dynamic_sql_invalid",
                f"SQL is not valid {dialect} SQL",
            ) from exc
        except SqlglotError as exc:
            raise DynamicSqlError(
                "dynamic_sql_invalid",
                f"SQL is not valid {dialect} SQL",
            ) from exc

        if len(statements) != 1 or statements[0] is None:
            raise DynamicSqlError(
                "dynamic_sql_multiple_statements",
                "Exactly one SQL statement is required",
            )

        expression = cast(exp.Expression, statements[0])
        _validate_select_tree(expression)
        canonical_sql = expression.sql(dialect=dialect, comments=False)
        if dialect == "postgres":
            canonical_sql = re.sub(
                r"%\(([A-Za-z_][A-Za-z0-9_]*)\)s",
                r":\1",
                canonical_sql,
            )
        reparsed = _parse_canonical_sql(canonical_sql, dialect=dialect)
        _validate_select_tree(reparsed)

        parameter_names: set[str] = set()
        for placeholder in reparsed.find_all(exp.Placeholder):
            name = placeholder.name
            if not _PARAMETER_NAME.fullmatch(name):
                raise DynamicSqlError(
                    "dynamic_sql_invalid_parameter",
                    "SQL parameters must use :name with an ASCII identifier",
                )
            parameter_names.add(name)

        return ValidatedSql(
            canonical_sql=canonical_sql,
            parameter_names=frozenset(parameter_names),
        )


def _validate_characters(sql: str) -> None:
    for character in sql:
        if character in _ALLOWED_CONTROL_CHARACTERS:
            continue
        if unicodedata.category(character).startswith("C"):
            raise DynamicSqlError(
                "dynamic_sql_unsafe_character",
                "SQL contains an unsafe control or formatting character",
            )


def _validate_select_tree(expression: exp.Expression) -> None:
    if not isinstance(expression, exp.Select):
        raise DynamicSqlError(
            "dynamic_sql_statement_not_allowed",
            "Only SELECT queries are allowed",
        )
    if any(isinstance(node, _FORBIDDEN_NODES) for node in expression.walk()):
        raise DynamicSqlError(
            "dynamic_sql_statement_not_allowed",
            "Only read-only SELECT expressions are allowed",
        )


def _parse_canonical_sql(
    canonical_sql: str,
    *,
    dialect: str,
) -> exp.Expression:
    try:
        expression = sqlglot.parse_one(
            canonical_sql,
            read=dialect,
            error_level=ErrorLevel.RAISE,
        )
    except SqlglotError as exc:
        raise DynamicSqlError(
            "dynamic_sql_invalid",
            "Canonical SQL could not be validated",
        ) from exc
    return cast(exp.Expression, expression)
