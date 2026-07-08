"""FastAPI routers for the public API."""

from fastapi import APIRouter

from humanoid_robot.core.api.adapters import router as adapters_router
from humanoid_robot.core.api.events import router as events_router
from humanoid_robot.core.api.system import router as system_router

router = APIRouter()
router.include_router(system_router, prefix="/system", tags=["system"])
router.include_router(adapters_router, prefix="/adapters", tags=["adapters"])
router.include_router(events_router, prefix="/events", tags=["events"])

__all__ = ["router"]
