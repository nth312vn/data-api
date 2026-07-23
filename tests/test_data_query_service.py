import asyncio
import logging
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.infrastructure.trino import TrinoColumn
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.repositories.interfaces.pii_mapping import PiiMappingRecord
from app.schemas.common import MissingPiiMapping
from app.schemas.power_bi import PowerBiDeeplinkRequest
from app.services.account_map_in_memory import AccountMapInMemory
from app.services.audit_log import AuditLogService
from app.services.query_engine import PiiMapper, PowerBiDataService, UsersDataService
from app.services.query_engine.base_service import BaseQueryService
from app.services.query_engine.pii_rules import QuerySpec
from app.services.query_engine.users_rules import USERS_PII_RULES


class FakeTrinoClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statement: Any | None = None
        self.sql: str | None = None
        self.params: dict[str, Any] = {}

    async def execute(self, statement: Any) -> list[dict[str, Any]]:
        self.statement = statement
        self.sql = str(statement)
        if hasattr(statement, "compile"):
            self.params = statement.compile().params
        return self.rows

    async def get_catalogs(self) -> list[str]:
        return []

    async def get_schemas(self, *, catalog: str) -> list[str]:
        return []

    async def get_tables(self, *, catalog: str, schema: str) -> list[str]:
        return []

    async def get_columns(
        self,
        *,
        catalog: str,
        schema: str,
        table: str,
    ) -> list[TrinoColumn]:
        return []


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.audit_logs: list[AuditLog] = []

    async def create(self, audit_log: AuditLog) -> AuditLog:
        self.audit_logs.append(audit_log)
        return audit_log


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class RowsOnlyResponse(BaseModel):
    items: list[dict[str, Any]]


def build_rows_only_response(
    rows: list[dict[str, Any]],
    _missing_mappings: tuple[MissingPiiMapping, ...],
) -> RowsOnlyResponse:
    return RowsOnlyResponse(items=rows)


class RaisingFakeTrinoClient(FakeTrinoClient):
    def __init__(self, error: BaseException) -> None:
        super().__init__(rows=[])
        self.error = error

    async def execute(self, statement: Any) -> list[dict[str, Any]]:
        self.statement = statement
        raise self.error


def make_user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        username="user",
        hashed_password="hash",
        role=UserRole.user,
    )


def make_pii_cache(
    records: list[PiiMappingRecord] | None = None,
) -> AccountMapInMemory:
    cache = AccountMapInMemory()
    if records:
        cache.add_records(records)
    return cache


def test_power_bi_request_normalizes_customer_ids() -> None:
    request = PowerBiDeeplinkRequest(
        customer_id=["VNH001,VNH002", " VNH003 "],
        segmentation=["VCB,ACB"],
        user_agent=["Android,Dalvik"],
    )

    assert request.customer_id == ["VNH001", "VNH002", "VNH003"]
    assert request.segmentation == ["VCB", "ACB"]
    assert request.user_agent == ["Android", "Dalvik"]


def test_power_bi_request_defaults_to_yesterday_through_today_without_limit() -> None:
    request = PowerBiDeeplinkRequest()

    assert request.start_date == date.today() - timedelta(days=1)
    assert request.end_date == date.today()
    assert request.limit is None


@pytest.mark.asyncio
async def test_execute_supports_response_without_missing_pii_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    trino = FakeTrinoClient([{"value": "sensitive-row-value"}])
    service = BaseQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mapper=PiiMapper(mapping_cache=make_pii_cache()),
        uow=FakeUnitOfWork(),
    )
    spec = QuerySpec(
        route_name="data.summary",
        statement="SELECT 'sensitive-sql-value' AS value",
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.services.query_engine.base_service",
    ):
        outcome = await service.execute(
            spec=spec,
            response_factory=build_rows_only_response,
        )

    assert outcome.response == RowsOnlyResponse(
        items=[{"value": "sensitive-row-value"}],
    )
    assert outcome.missing_mappings == ()
    assert "route_name=data.summary status=success" in caplog.text
    assert "response_type=RowsOnlyResponse" in caplog.text
    assert "row_count=1" in caplog.text
    assert "pii_applied=false" in caplog.text
    assert "missing_mapping_count=0" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "sensitive-sql-value" not in caplog.text
    assert "sensitive-row-value" not in caplog.text


@pytest.mark.asyncio
async def test_execute_keeps_missing_pii_outside_response_model() -> None:
    unmapped_value = "m" * 32
    service = BaseQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=FakeTrinoClient([{"customer_id": unmapped_value}]),
        pii_mapper=PiiMapper(mapping_cache=make_pii_cache()),
        uow=FakeUnitOfWork(),
    )
    spec = QuerySpec(
        route_name="data.summary_with_pii",
        statement="SELECT customer_id FROM users",
        column_pii_rules=USERS_PII_RULES,
    )

    outcome = await service.execute(
        spec=spec,
        response_factory=build_rows_only_response,
    )

    assert outcome.response.model_dump() == {"items": [{"customer_id": None}]}
    assert outcome.missing_mappings == (
        MissingPiiMapping(column_name="customer_id", value=unmapped_value),
    )


@pytest.mark.asyncio
async def test_execute_logs_failed_query_and_reraises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = BaseQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=RaisingFakeTrinoClient(RuntimeError("sensitive failure detail")),
        pii_mapper=PiiMapper(mapping_cache=make_pii_cache()),
        uow=FakeUnitOfWork(),
    )
    spec = QuerySpec(route_name="data.failed", statement="SELECT secret")

    with (
        caplog.at_level(
            logging.ERROR,
            logger="app.services.query_engine.base_service",
        ),
        pytest.raises(RuntimeError, match="sensitive failure detail"),
    ):
        await service.execute(
            spec=spec,
            response_factory=build_rows_only_response,
        )

    assert "route_name=data.failed status=failed" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "pii_applied=false" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "SELECT secret" not in caplog.text
    assert "sensitive failure detail" not in caplog.text


@pytest.mark.asyncio
async def test_execute_logs_cancelled_query_and_reraises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = BaseQueryService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=RaisingFakeTrinoClient(asyncio.CancelledError()),
        pii_mapper=PiiMapper(mapping_cache=make_pii_cache()),
        uow=FakeUnitOfWork(),
    )
    spec = QuerySpec(route_name="data.cancelled", statement="SELECT 1")

    with (
        caplog.at_level(
            logging.WARNING,
            logger="app.services.query_engine.base_service",
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await service.execute(
            spec=spec,
            response_factory=build_rows_only_response,
        )

    assert "route_name=data.cancelled status=cancelled" in caplog.text
    assert "pii_applied=false" in caplog.text
    assert "duration_ms=" in caplog.text


@pytest.mark.asyncio
async def test_query_maps_pii_from_cache_and_database() -> None:
    cache = make_pii_cache(
        [
            PiiMappingRecord(
                token="c" * 31 + "1",
                mapped_value="7c37bb4b-0e15-4fb9-b589-f57211ac1679",
            ),
            PiiMappingRecord(
                token="c" * 31 + "2",
                mapped_value="adf349fb-bbfc-4102-96a1-65af0b063389",
            ),
        ],
    )
    uow = FakeUnitOfWork()
    trino = FakeTrinoClient(
        [
            {"customer_id": "c" * 31 + "1", "amount": 100},
            {"customer_id": "c" * 31 + "2", "amount": 200},
        ],
    )
    pii_mapper = PiiMapper(mapping_cache=cache)
    service = UsersDataService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mapper=pii_mapper,
        uow=uow,
    )

    outcome = await service.list_users(
        limit=50,
        offset=10,
    )

    assert outcome.response.rows == [
        {
            "customer_id": "7c37bb4b-0e15-4fb9-b589-f57211ac1679",
            "amount": 100,
        },
        {
            "customer_id": "adf349fb-bbfc-4102-96a1-65af0b063389",
            "amount": 200,
        },
    ]
    assert outcome.missing_mappings == ()
    assert uow.commits == 0
    assert trino.sql is not None
    assert 'FROM "hive"."default"."users"' in trino.sql
    assert "LIMIT 50" in trino.sql
    assert "OFFSET 10" in trino.sql


@pytest.mark.asyncio
async def test_query_returns_null_for_unmapped_pii_values() -> None:
    unmapped_value = "m" * 32
    uow = FakeUnitOfWork()
    mapping_cache = make_pii_cache()
    pii_mapper = PiiMapper(mapping_cache=mapping_cache)
    service = UsersDataService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=FakeTrinoClient([{"customer_id": unmapped_value}]),
        pii_mapper=pii_mapper,
        uow=uow,
    )

    outcome = await service.list_users(
        limit=100,
        offset=0,
    )

    assert outcome.response.rows == [{"customer_id": None}]
    assert outcome.missing_mappings == (
        MissingPiiMapping(
            column_name="customer_id",
            value=unmapped_value,
        ),
    )
    assert outcome.response.missing_mappings == list(outcome.missing_mappings)

    audit_repository = FakeAuditLogRepository()
    audit_uow = FakeUnitOfWork()
    audit_service = AuditLogService(
        audit_logs=audit_repository,
        uow=audit_uow,
    )
    await audit_service.audit_missing_mappings(
        actor=make_user(),
        route_name="data.users",
        request_parameters={"limit": 100, "offset": 0},
        missing_mappings=list(outcome.missing_mappings),
    )

    assert audit_repository.audit_logs[0].parameters == {
        "limit": 100,
        "offset": 0,
        "missing_mappings": [
            {
                "column_name": "customer_id",
                "value": unmapped_value,
            }
        ],
    }
    assert audit_uow.commits == 1


@pytest.mark.asyncio
async def test_query_maps_value_when_present_in_cache() -> None:
    mapping_cache = make_pii_cache(
        [PiiMappingRecord(token="m" * 32, mapped_value="resolved-uuid")],
    )
    pii_mapper = PiiMapper(mapping_cache=mapping_cache)
    service = UsersDataService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=FakeTrinoClient([{"customer_id": "m" * 32}]),
        pii_mapper=pii_mapper,
        uow=FakeUnitOfWork(),
    )

    outcome = await service.list_users(limit=100, offset=0)

    assert outcome.response.rows == [{"customer_id": "resolved-uuid"}]
    assert outcome.missing_mappings == ()


@pytest.mark.asyncio
async def test_query_keeps_null_pii_values_without_mapping() -> None:
    mapping_cache = make_pii_cache()
    pii_mapper = PiiMapper(mapping_cache=mapping_cache)
    service = UsersDataService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=FakeTrinoClient([{"customer_id": None}]),
        pii_mapper=pii_mapper,
        uow=FakeUnitOfWork(),
    )

    outcome = await service.list_users(limit=100, offset=0)

    assert outcome.response.rows == [{"customer_id": None}]
    assert outcome.missing_mappings == ()


@pytest.mark.asyncio
async def test_pii_mapper_raises_when_spec_has_no_mapping_rules() -> None:
    pii_mapper = PiiMapper(mapping_cache=AccountMapInMemory())
    spec = QuerySpec(route_name="data.no_pii", statement="SELECT 1")

    with pytest.raises(ValueError, match="has no PII mapping rules"):
        await pii_mapper.map_pii_fields(rows=[{"customer_id": "m" * 32}], spec=spec)


@pytest.mark.asyncio
async def test_power_bi_deeplink_1_builds_topup_result_query() -> None:
    trino = FakeTrinoClient(
        [
            {
                "stt": 1,
                "accountid": "v" * 32 + "X",
            }
        ],
    )
    cache = make_pii_cache(
        [
            PiiMappingRecord(
                token="v" * 32,
                mapped_value="7c37bb4b-0e15-4fb9-b589-f57211ac1679",
            )
        ],
    )
    pii_mapper = PiiMapper(mapping_cache=cache)
    service = PowerBiDataService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mapper=pii_mapper,
        uow=FakeUnitOfWork(),
    )

    outcome = await service.deeplink_1(
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        limit=1000,
        customer_ids=("7c37bb4b-0e15-4fb9-b589-f57211ac1679X",),
    )

    assert outcome.response.rows == [
        {"stt": 1, "accountid": "7c37bb4b-0e15-4fb9-b589-f57211ac1679X"}
    ]
    assert outcome.missing_mappings == ()
    assert trino.sql is not None
    assert "FROM hive.wh_cpm.cpm_event_raw" in trino.sql
    assert "LEFT OUTER JOIN hive.wh_bo_hudi.t_cust_customer" in trino.sql
    assert "hive.wh_cpm.cpm_event_raw.key = :key_1" in trino.sql
    assert "hive.wh_cpm.cpm_event_raw.accountid IN" in trino.sql
    assert " LIMIT " in trino.sql
    assert "AS event_time" in trino.sql
    assert "AS bank_name" in trino.sql
    assert trino.params["key_1"] == "topup_result"
    assert trino.params["element_at_3"] == "deeplink"
    assert trino.params["date_1"] == date(2026, 6, 1)
    assert trino.params["date_2"] == date(2026, 6, 2)
    assert trino.params["element_at_5"] == "processing"
    assert trino.params["param_4"] == 1000


@pytest.mark.asyncio
async def test_power_bi_deeplink_2_builds_topup_bank_app_query() -> None:
    trino = FakeTrinoClient(
        [
            {"stt": 1, "accountid": "v" * 32 + "X"},
            {"stt": 2, "accountid": "v" * 32},
        ],
    )
    cache = make_pii_cache(
        [
            PiiMappingRecord(
                token="v" * 32,
                mapped_value="7c37bb4b-0e15-4fb9-b589-f57211ac1679",
            )
        ],
    )
    pii_mapper = PiiMapper(mapping_cache=cache)
    service = PowerBiDataService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mapper=pii_mapper,
        uow=FakeUnitOfWork(),
    )

    outcome = await service.deeplink_2(
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        limit=None,
    )

    assert outcome.response.rows == [
        {"stt": 1, "accountid": "7c37bb4b-0e15-4fb9-b589-f57211ac1679X"},
        {"stt": 2, "accountid": "7c37bb4b-0e15-4fb9-b589-f57211ac1679"},
    ]
    assert outcome.missing_mappings == ()
    assert trino.sql is not None
    assert "hive.wh_cpm.cpm_event_raw.key = :key_1" in trino.sql
    assert "hive.wh_cpm.cpm_event_raw.accountid IN" not in trino.sql
    assert trino.params["key_1"] == "topup_bank_app"
    assert trino.params["element_at_3"] == "deeplink"
    assert "processing" not in trino.params.values()
    assert " LIMIT " not in trino.sql


@pytest.mark.asyncio
async def test_power_bi_pushes_non_pii_filters_and_limit_to_trino() -> None:
    first_uuid = "7c37bb4b-0e15-4fb9-b589-f57211ac1679"
    trino = FakeTrinoClient(
        [
            {
                "stt": 1,
                "accountid": "v" * 32 + "X",
                "bank_name": "VCB",
            },
        ],
    )
    mapping_cache = make_pii_cache(
        [PiiMappingRecord(token="v" * 32, mapped_value=first_uuid)],
    )
    pii_mapper = PiiMapper(mapping_cache=mapping_cache)
    service = PowerBiDataService(
        settings=Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars"),
        trino=trino,
        pii_mapper=pii_mapper,
        uow=FakeUnitOfWork(),
    )

    outcome = await service.deeplink_2(
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        limit=1,
        segmentation_filters=("VCB",),
        user_agent_filters=("IOS", "android"),
        customer_ids=(first_uuid + "X",),
    )

    assert outcome.response.rows == [
        {
            "stt": 1,
            "accountid": first_uuid + "X",
            "bank_name": "VCB",
        }
    ]
    assert outcome.missing_mappings == ()
    assert trino.sql is not None
    assert "hive.wh_cpm.cpm_event_raw.accountid IN" in trino.sql
    assert "lower(element_at(hive.wh_cpm.cpm_event_raw.segmentation" in trino.sql
    assert "lower(CASE WHEN" in trino.sql
    assert " LIMIT " in trino.sql
    assert "bank_name" in trino.params.values()
    assert trino.params["lower_5"] == ["vcb"]
    assert trino.params["lower_6"] == ["ios", "android"]
    assert trino.params["param_4"] == 1
