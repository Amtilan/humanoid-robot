"""FastAPI routers for the public API."""

from fastapi import APIRouter

from humanoid_robot.core.api.system import router as system_router

router = APIRouter()
router.include_router(system_router, prefix="/system", tags=["system"])

__all__ = ["router"]
