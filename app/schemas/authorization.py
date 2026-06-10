from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ApiPermissionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    route_prefix: str = Field(min_length=1, max_length=255)
    is_active: bool = True

    @field_validator("route_prefix")
    @classmethod
    def validate_route_prefix(cls, value: str) -> str:
        route_prefix = value.strip()
        if not route_prefix.startswith("/"):
            raise ValueError("route_prefix must start with '/'")
        return route_prefix.rstrip("/") or "/"


class ApiPermissionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    route_prefix: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None

    @field_validator("route_prefix")
    @classmethod
    def validate_route_prefix(cls, value: str | None) -> str | None:
        if value is None:
            return value
        route_prefix = value.strip()
        if not route_prefix.startswith("/"):
            raise ValueError("route_prefix must start with '/'")
        return route_prefix.rstrip("/") or "/"


class ApiPermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    route_prefix: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserRoleAssign(BaseModel):
    role_id: UUID


class UserPermissionAssign(BaseModel):
    permission_id: UUID
