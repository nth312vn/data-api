from datetime import date, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import TextClause
from starlette.datastructures import QueryParams

from app.services.query_engine.dynamic_parameters import (
    DynamicParameterDefinition,
    DynamicParameterError,
    build_bound_statement,
    cast_parameter_values,
    validate_parameter_contract,
)


def test_parameter_definition_rejects_default_for_required_parameter() -> None:
    with pytest.raises(ValidationError):
        DynamicParameterDefinition(type="integer", required=True, default=5)


def test_parameter_definition_validates_optional_default_type() -> None:
    definition = DynamicParameterDefinition(
        type="date",
        required=False,
        default="2026-07-01",
    )

    assert definition.default == "2026-07-01"

    with pytest.raises(ValidationError):
        DynamicParameterDefinition(
            type="integer",
            required=False,
            default="not-an-integer",
        )


def test_contract_requires_exact_placeholder_and_definition_names() -> None:
    definitions = {
        "region": DynamicParameterDefinition(type="string"),
        "unused": DynamicParameterDefinition(type="string"),
    }

    with pytest.raises(DynamicParameterError) as exc_info:
        validate_parameter_contract(frozenset({"region", "missing"}), definitions)

    assert exc_info.value.code == "dynamic_parameter_contract_mismatch"
    assert exc_info.value.details == {
        "missing_definitions": ["missing"],
        "unused_definitions": ["unused"],
    }


def test_cast_parameter_values_supports_all_scalar_types() -> None:
    definitions = {
        "name": DynamicParameterDefinition(type="string"),
        "count": DynamicParameterDefinition(type="integer"),
        "ratio": DynamicParameterDefinition(type="float"),
        "enabled": DynamicParameterDefinition(type="boolean"),
        "day": DynamicParameterDefinition(type="date"),
        "at": DynamicParameterDefinition(type="datetime"),
    }
    values = cast_parameter_values(
        definitions,
        QueryParams(
            "name=APAC&count=12&ratio=1.5&enabled=true"
            "&day=2026-07-01&at=2026-07-01T08%3A30%3A00%2B07%3A00"
        ),
    )

    assert values == {
        "name": "APAC",
        "count": 12,
        "ratio": 1.5,
        "enabled": True,
        "day": date(2026, 7, 1),
        "at": datetime.fromisoformat("2026-07-01T08:30:00+07:00"),
    }


def test_cast_string_list_supports_repeated_and_comma_separated_values() -> None:
    definitions = {
        "regions": DynamicParameterDefinition(type="string_list"),
    }

    values = cast_parameter_values(
        definitions,
        QueryParams("regions=APAC%2CEU&regions=US"),
    )

    assert values == {"regions": ["APAC", "EU", "US"]}


def test_cast_parameter_values_uses_optional_default() -> None:
    definitions = {
        "limit": DynamicParameterDefinition(
            type="integer",
            required=False,
            default="25",
        ),
    }

    assert cast_parameter_values(definitions, QueryParams()) == {"limit": 25}


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("", "dynamic_parameter_missing"),
        ("limit=1&extra=value", "dynamic_parameter_unknown"),
        ("limit=one", "dynamic_parameter_invalid"),
        ("limit=1&limit=2", "dynamic_parameter_invalid"),
    ],
)
def test_cast_parameter_values_rejects_bad_runtime_input(
    query: str,
    code: str,
) -> None:
    definitions = {"limit": DynamicParameterDefinition(type="integer")}

    with pytest.raises(DynamicParameterError) as exc_info:
        cast_parameter_values(definitions, QueryParams(query))

    assert exc_info.value.code == code


def test_injection_payload_remains_a_bound_string_value() -> None:
    payload = "APAC' OR 1=1 --"
    definitions = {"region": DynamicParameterDefinition(type="string")}
    values = cast_parameter_values(
        definitions,
        QueryParams({"region": payload}),
    )
    statement = build_bound_statement(
        "SELECT * FROM sales WHERE region = :region",
        definitions,
    )

    assert isinstance(statement, TextClause)
    assert payload not in statement.text
    assert values == {"region": payload}
    assert "region" in statement._bindparams


def test_string_list_uses_expanding_bind_instead_of_interpolation() -> None:
    definitions = {
        "regions": DynamicParameterDefinition(type="string_list"),
    }
    statement = build_bound_statement(
        "SELECT * FROM sales WHERE region IN (:regions)",
        definitions,
    )

    assert statement._bindparams["regions"].expanding is True
    assert "POSTCOMPILE_regions" in str(statement.compile())
