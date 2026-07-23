from app.core.config import Settings
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.trino.client import TrinoClient
from app.services.query_engine.pii_mapper import PiiMapper


class BaseQueryService:
    def __init__(
        self,
        *,
        settings: Settings,
        trino: TrinoClient,
        pii_mapper: PiiMapper,
        uow: UnitOfWork,
    ) -> None:
        self.settings = settings
        self.trino = trino
        self.pii_mapper = pii_mapper
        self.uow = uow

    def _get_tokens_by_original_values(
        self,
        *,
        original_values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not original_values:
            return ()
        lower_values = {v.casefold() for v in original_values}
        cache = self.pii_mapper.mapping_cache.value_to_token
        tokens = [
            token
            for mapped_value, token in cache.items()
            if mapped_value.casefold() in lower_values
        ]
        if not tokens:
            # Return a dummy token so the query will return an empty result
            # rather than skipping the filter entirely.
            return ("__NO_MATCH__",)
        return tuple(tokens)
