from collections.abc import Iterable, Iterator
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pii_models import CustomerIdentityPiiMapping
from app.repositories.interfaces.pii_mapping import PiiMappingRecord


class SQLAlchemyAccountMapRepository:
    def __init__(
        self,
        *,
        session: AsyncSession,
        query_batch_size: int = 500,
    ) -> None:
        if query_batch_size <= 0:
            raise ValueError("query_batch_size must be greater than zero")
        self.session = session
        self.query_batch_size = query_batch_size

    async def get_many(
        self,
        *,
        tokens: set[str],
    ) -> dict[str, PiiMappingRecord]:
        if not tokens:
            return {}

        customer = CustomerIdentityPiiMapping
        mappings: dict[str, PiiMappingRecord] = {}
        for token_batch in self._batches(sorted(tokens), self.query_batch_size):
            stmt = select(
                customer.customer_id.label("token"),
                customer.uuid.label("mapped_value"),
                customer.created_at.label("created_at"),
            ).where(customer.customer_id.in_(token_batch))

            result = await self.session.execute(stmt)
            for row in result.mappings():
                token = str(row["token"])
                mappings[token] = PiiMappingRecord(
                    token=token,
                    mapped_value=str(row["mapped_value"]),
                    created_at=row["created_at"],
                )

        return mappings

    async def get_mappings_batch(
        self,
        *,
        limit: int,
        offset: int,
        since: datetime | None = None,
    ) -> list[PiiMappingRecord]:
        """Fetch a batch of account mapping records using offset pagination."""
        customer = CustomerIdentityPiiMapping

        stmt = select(
            customer.customer_id.label("token"),
            customer.uuid.label("mapped_value"),
            customer.created_at.label("created_at"),
        )

        if since is not None:
            stmt = stmt.where(customer.created_at > since)

        stmt = stmt.order_by(customer.created_at, customer.customer_id)
        stmt = stmt.limit(limit).offset(offset)

        records: list[PiiMappingRecord] = []
        result = await self.session.execute(stmt)
        for row in result.mappings():
            records.append(
                PiiMappingRecord(
                    token=str(row["token"]),
                    mapped_value=str(row["mapped_value"]),
                    created_at=row["created_at"],
                )
            )

        return records

    def _batches(self, values: Iterable[str], size: int) -> Iterator[tuple[str, ...]]:
        batch: list[str] = []
        for value in values:
            batch.append(value)
            if len(batch) == size:
                yield tuple(batch)
                batch = []
        if batch:
            yield tuple(batch)
