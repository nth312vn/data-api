from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class ConflictError(AppError):
    def __init__(self, message: str, code: str = "conflict") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            message=message,
        )


class AuthenticationError(AppError):
    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="authentication_failed",
            message=message,
        )


class AuthorizationError(AppError):
    def __init__(self, message: str = "Not enough permissions") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code="not_enough_permissions",
            message=message,
        )


class NotFoundError(AppError):
    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
            message=f"{resource} not found",
        )


class ExternalServiceTimeoutError(AppError):
    def __init__(self, service_name: str) -> None:
        super().__init__(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            code="external_service_timeout",
            message=f"{service_name} timed out",
        )


def error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | list[Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or {},
                    "request_id": getattr(request.state, "request_id", None),
                },
            },
            custom_encoder={bytes: _decode_bytes},
        ),
    )


def _decode_bytes(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def validation_error_details(
    errors: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {"errors": [_format_validation_error(error) for error in errors]}


def _format_validation_error(error: Mapping[str, Any]) -> dict[str, Any]:
    loc = _normalize_error_location(error.get("loc", ()))
    field_parts = [
        str(part)
        for part in loc
        if str(part) not in {"body", "query", "path", "header", "cookie"}
    ]
    field = ".".join(field_parts) if field_parts else "request"
    formatted_error: dict[str, Any] = {
        "field": field,
        "message": str(error.get("msg", "Invalid value")),
        "type": str(error.get("type", "value_error")),
    }
    if "input" in error:
        formatted_error["input"] = error["input"]
    return formatted_error


def _normalize_error_location(value: Any) -> tuple[Any, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    if value:
        return (value,)
    return ()


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_exception(
        request: Request,
        exc: AppError,
    ) -> JSONResponse:
        return error_response(
            request=request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            request=request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="Invalid request payload",
            details=validation_error_details(exc.errors()),
        )

    @app.exception_handler(ValidationError)
    async def handle_pydantic_validation_exception(
        request: Request,
        exc: ValidationError,
    ) -> JSONResponse:
        return error_response(
            request=request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="Invalid request payload",
            details=validation_error_details(exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        phrase = HTTPStatus(exc.status_code).phrase
        return error_response(
            request=request,
            status_code=exc.status_code,
            code="http_error",
            message=phrase,
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_exception(
        request: Request,
        exc: SQLAlchemyError,
    ) -> JSONResponse:
        logger.exception("database_error", exc_info=exc)
        return error_response(
            request=request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_server_error",
            message="Internal server error",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("unexpected_error", exc_info=exc)
        return error_response(
            request=request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_server_error",
            message="Internal server error",
        )
