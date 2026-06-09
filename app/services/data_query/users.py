from app.utils.sql import quote_identifier_path

USERS_SOURCE_TABLE = quote_identifier_path("hive.default.users")


def build_users_query(*, limit: int, offset: int) -> str:
    sql = f"""
        SELECT
            user_id,
            customer_id,
            full_name,
            created_at
        FROM {USERS_SOURCE_TABLE}
        ORDER BY created_at DESC
        OFFSET {offset}
        LIMIT {limit}
    """  # noqa: S608
    return sql
