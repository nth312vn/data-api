from pydantic import BaseModel


class HealthCheck(BaseModel):
    status: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object] | list[object]
    request_id: str | None = None
