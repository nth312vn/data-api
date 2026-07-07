"""PII column rules cho Power BI service.

Mỗi service define cụ thể column nào cần PII transform và dùng transformer nào.
"""

from app.services.query_engine.pii_rules import PiiColumnRule, transform_by_token_length

POWER_BI_ACCOUNT_PII_RULES = {
    "accountid": PiiColumnRule(
        pii_category="accountid",
        transformer=transform_by_token_length,
    ),
}
