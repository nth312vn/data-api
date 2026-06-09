from dataclasses import dataclass

from sqlalchemy.sql import Executable


@dataclass(frozen=True, slots=True)
class DataRouteSpec:
    route_name: str
    source_system: str
    statement: str | Executable
    pii_fields: tuple[str, ...]
