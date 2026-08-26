from fastapi import APIRouter

from src.api.incidents import router as incident_router

router = APIRouter()
router.include_router(incident_router)


@router.get("/status")
async def agent_status():
    """Kiểm tra trạng thái agent."""
    return {"status": "ready", "agent": "LangGraph Agent v1.0"}
