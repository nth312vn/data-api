import re

IDENTIFIER_PATH_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$",
)


def quote_identifier_path(identifier_path: str) -> str:
    if not IDENTIFIER_PATH_PATTERN.fullmatch(identifier_path):
        raise ValueError(f"Invalid SQL identifier path: {identifier_path}")
    return ".".join(f'"{part}"' for part in identifier_path.split("."))
