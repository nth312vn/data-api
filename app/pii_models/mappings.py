from sqlalchemy import CHAR, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.pii_models.base import PiiBase, PiiMappingModelMixin


class CustomerIdentityPiiMapping(PiiMappingModelMixin, PiiBase):
    __tablename__ = "customer_identity_map"

    __pii_type__ = "customer_id"
    __pii_token_attr__ = "customer_id"
    __pii_value_attr__ = "uuid"

    customer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False)


PII_MAPPING_MODELS: dict[str, type[PiiMappingModelMixin]] = {
    model.__pii_type__: model for model in (CustomerIdentityPiiMapping,)
}
