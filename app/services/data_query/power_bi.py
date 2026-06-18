from datetime import date

from sqlalchemy import (
    BigInteger,
    Column,
    MetaData,
    String,
    Table,
    case,
    func,
    or_,
    select,
)
from sqlalchemy.sql import Executable
from sqlalchemy.sql.elements import quoted_name

POWER_BI_METADATA = MetaData()
POWER_BI_CATALOG = "hive"
POWER_BI_EVENT_TABLE = Table(
    "cpm_event_raw",
    POWER_BI_METADATA,
    Column("timestamp", BigInteger),
    Column("segmentation", String),
    Column("accountid", String),
    Column("user_agent", String),
    Column("key", String),
    schema=quoted_name(f"{POWER_BI_CATALOG}.wh_cpm", quote=False),
)
POWER_BI_CUSTOMER_TABLE = Table(
    "t_cust_customer",
    POWER_BI_METADATA,
    Column("c_customer_code", String),
    Column("c_cust_full_name", String),
    schema=quoted_name(f"{POWER_BI_CATALOG}.wh_bo_hudi", quote=False),
)


def build_power_bi_deeplink_query(
    *,
    event_key: str,
    start_date: date,
    end_date: date,
    segmentation_filters: tuple[str, ...] = (),
    user_agent_filters: tuple[str, ...] = (),
    limit: int | None = None,
    status: str | None = None,
) -> Executable:
    event_raw = POWER_BI_EVENT_TABLE
    customer = POWER_BI_CUSTOMER_TABLE
    event_timestamp = event_raw.c["timestamp"]
    segmentation = event_raw.c["segmentation"]
    account_id = event_raw.c["accountid"]
    user_agent = event_raw.c["user_agent"]

    conditions = [
        event_raw.c["key"] == event_key,
        func.element_at(segmentation, "bank_method") == "deeplink",
        func.date(func.from_unixtime(event_timestamp / 1000)).between(
            start_date,
            end_date,
        ),
    ]
    if status is not None:
        conditions.append(func.element_at(segmentation, "status") == status)
    if segmentation_filters:
        conditions.append(
            func.lower(func.element_at(segmentation, "bank_name")).in_(
                [value.casefold() for value in segmentation_filters],
            ),
        )
    if user_agent_filters:
        conditions.append(
            or_(
                *(
                    func.lower(user_agent).contains(
                        filter_value.casefold(),
                        autoescape=True,
                    )
                    for filter_value in user_agent_filters
                ),
            ),
        )

    statement = (
        select(
            func.row_number().over(order_by=event_timestamp).label("stt"),
            func.date_format(
                func.from_unixtime(event_timestamp / 1000),
                "%Y-%m-%d %H:%i:%s",
            ).label("event_time"),
            func.element_at(segmentation, "bank_name").label("bank_name"),
            account_id,
            customer.c["c_cust_full_name"],
            case(
                (
                    or_(
                        func.lower(user_agent).like("%android%"),
                        func.lower(user_agent).like("%dalvik%"),
                    ),
                    "Android",
                ),
                (
                    or_(
                        func.lower(user_agent).like("%cfnetwork%"),
                        func.lower(user_agent).like("%darwin%"),
                    ),
                    "iOS",
                ),
                else_="Other",
            ).label("device"),
        )
        .select_from(
            event_raw.outerjoin(
                customer,
                account_id == customer.c["c_customer_code"],
            ),
        )
        .where(*conditions)
        .order_by(event_timestamp)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return statement
