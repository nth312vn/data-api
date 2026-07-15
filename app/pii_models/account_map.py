from datetime import datetime

from sqlalchemy import CHAR, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.pii_models.base import PiiBase


class CustomerIdentityPiiMapping(PiiBase):
    __tablename__ = "account_map"

    customer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
