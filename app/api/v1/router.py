from fastapi import APIRouter, Depends

from app.api.v1.endpoints import (
    auth,
    data,
    dynamic_execute,
    dynamic_routes,
    health,
    power_bi,
    users,
)
from app.dependencies.auth import require_api_permission

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_api_permission)],
)
api_router.include_router(
    data.router,
    prefix="/data",
    tags=["data"],
    dependencies=[Depends(require_api_permission)],
)
api_router.include_router(
    power_bi.router,
    prefix="/power_bi",
    tags=["power_bi"],
    dependencies=[Depends(require_api_permission)],
)
api_router.include_router(
    dynamic_routes.router,
    prefix="/dynamic-routes",
    tags=["dynamic-routes"],
)
api_router.include_router(
    dynamic_execute.router,
    tags=["dynamic-execution"],
)
