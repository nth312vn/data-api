from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.pii_models.base import PiiBase, PiiMappingModelMixin


class EmailPiiMapping(PiiMappingModelMixin, PiiBase):
    __tablename__ = "pii_email_lookup"

    __pii_type__ = "email_token"
    __pii_token_attr__ = "email_hash"
    __pii_value_attr__ = "email_address"
    __pii_source_attr__ = "system_code"

    email_hash: Mapped[str] = mapped_column(String(512), primary_key=True)
    system_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)


class PhonePiiMapping(PiiMappingModelMixin, PiiBase):
    __tablename__ = "pii_phone_lookup"

    __pii_type__ = "phone_token"
    __pii_token_attr__ = "phone_key"
    __pii_value_attr__ = "phone_number"

    phone_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(50), nullable=False)


class CustomerIdentityPiiMapping(PiiMappingModelMixin, PiiBase):
    __tablename__ = "customer_identity_map"

    __pii_type__ = "customer_id"
    __pii_token_attr__ = "customer_surrogate_id"
    __pii_value_attr__ = "customer_id"

    customer_surrogate_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False)


PII_MAPPING_MODELS: dict[str, type[PiiMappingModelMixin]] = {
    model.__pii_type__: model
    for model in (
        EmailPiiMapping,
        PhonePiiMapping,
        CustomerIdentityPiiMapping,
    )
}
