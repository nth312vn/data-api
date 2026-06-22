from datetime import date, timedelta
from typing import Any, Self

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


def default_start_date() -> date:
    return date.today() - timedelta(days=1)


class PowerBiDeeplinkRequest(BaseModel):
    start_date: date = Field(default_factory=default_start_date)
    end_date: date = Field(default_factory=date.today)
    limit: int | None = Field(default=None, ge=1)
    segmentation: list[str] = Field(default_factory=list)
    user_agent: list[str] = Field(default_factory=list)
    customer_id: list[str] = Field(default_factory=list)

    @field_validator(
        "segmentation",
        "user_agent",
        "customer_id",
        mode="before",
    )
    @classmethod
    def normalize_filter_values(
        cls,
        value: Any,
        info: ValidationInfo,
    ) -> list[str]:
        field_name = info.field_name or "filter"
        if value is None:
            return []
        if isinstance(value, str):
            return cls._split_filter_values([value], field_name=field_name)
        if isinstance(value, list):
            return cls._split_filter_values(value, field_name=field_name)
        raise ValueError(f"{field_name} must be a string or list of strings")

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be before or equal to end_date")
        return self

    @classmethod
    def _split_filter_values(
        cls,
        values: list[Any],
        *,
        field_name: str,
    ) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must contain only strings")
            normalized.extend(item.strip() for item in value.split(",") if item.strip())
        return normalized
