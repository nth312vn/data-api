from datetime import date
from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class PowerBiDeeplinkRequest(BaseModel):
    start_date: date = date(2026, 6, 1)
    end_date: date = date(2026, 6, 2)
    limit: int = Field(default=1000, ge=1, le=10000)
    customer_id: list[str] = Field(default_factory=list)

    @field_validator("customer_id", mode="before")
    @classmethod
    def normalize_customer_id(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return cls._split_customer_ids([value])
        if isinstance(value, list):
            return cls._split_customer_ids(value)
        raise ValueError("customer_id must be a string or list of strings")

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be before or equal to end_date")
        return self

    @classmethod
    def _split_customer_ids(cls, values: list[Any]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("customer_id must contain only strings")
            normalized.extend(item.strip() for item in value.split(",") if item.strip())
        return normalized
