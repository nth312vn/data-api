from fastapi import APIRouter

from app.api.v1.endpoints import auth, data, health, power_bi, users

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(data.router, prefix="/data", tags=["data"])
api_router.include_router(power_bi.router, prefix="/power_bi", tags=["power_bi"])
