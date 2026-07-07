"""PII column rules cho Users service.

Mỗi service define cụ thể column nào cần PII transform và dùng transformer nào.
"""

from app.services.query_engine.pii_rules import PiiColumnRule, transform_by_token_length

USERS_PII_RULES = {
    "customer_id": PiiColumnRule(
        pii_category="customer_id",
        transformer=transform_by_token_length,
    ),
}
