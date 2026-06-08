from typing import ClassVar

from sqlalchemy.orm import DeclarativeBase


class PiiBase(DeclarativeBase):
    pass


class PiiMappingModelMixin:
    __pii_type__: ClassVar[str]
    __pii_token_attr__: ClassVar[str]
    __pii_value_attr__: ClassVar[str]
    __pii_source_attr__: ClassVar[str | None] = None
    __pii_source_value__: ClassVar[str | None] = None
