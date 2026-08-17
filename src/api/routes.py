import logging

from fastapi import APIRouter, Depends, HTTPException

from src.agents.graph import agent
from src.models.schemas import ChatRequest, ChatResponse
from src.api.security import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat với AI agent."""
    try:
        result = await agent.ainvoke({"query": request.message})
        return ChatResponse(
            response=result.get("response", ""),
            analysis=result.get("analysis", ""),
        )
    except Exception:
        # Keep implementation details and upstream errors out of the public
        # response. The protected server log can be used for investigation.
        logger.exception("agent request failed")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from None


@router.get("/status")
async def agent_status():
    """Kiểm tra trạng thái agent."""
    return {"status": "ready", "agent": "LangGraph Agent v1.0"}
