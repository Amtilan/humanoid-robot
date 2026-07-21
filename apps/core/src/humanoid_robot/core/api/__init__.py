"""FastAPI routers for the public API."""

from fastapi import APIRouter

from humanoid_robot.core.api.adapters import router as adapters_router
from humanoid_robot.core.api.diagnostics import router as diagnostics_router
from humanoid_robot.core.api.events import router as events_router
from humanoid_robot.core.api.knowledge import router as knowledge_router
from humanoid_robot.core.api.llm import router as llm_router
from humanoid_robot.core.api.plugins import router as plugins_router
from humanoid_robot.core.api.rag import router as rag_router
from humanoid_robot.core.api.robot import router as robot_router
from humanoid_robot.core.api.safety import router as safety_router
from humanoid_robot.core.api.settings import router as settings_router
from humanoid_robot.core.api.system import router as system_router
from humanoid_robot.core.api.visits import router as visits_router
from humanoid_robot.core.api.voice import router as voice_router

router = APIRouter()
router.include_router(system_router, prefix="/system", tags=["system"])
router.include_router(adapters_router, prefix="/adapters", tags=["adapters"])
router.include_router(events_router, prefix="/events", tags=["events"])
router.include_router(plugins_router, prefix="/plugins", tags=["plugins"])
router.include_router(robot_router, prefix="/robot", tags=["robot"])
router.include_router(rag_router, prefix="/rag", tags=["rag"])
router.include_router(voice_router, prefix="/voice", tags=["voice"])
router.include_router(visits_router, prefix="/visits", tags=["visits"])
router.include_router(llm_router, prefix="/llm", tags=["llm"])
router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
router.include_router(diagnostics_router, prefix="/diagnostics", tags=["diagnostics"])
router.include_router(safety_router, prefix="/safety", tags=["safety"])
router.include_router(settings_router, prefix="/settings", tags=["settings"])

__all__ = ["router"]
