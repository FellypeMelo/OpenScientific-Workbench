from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from uuid import UUID
import asyncio

router = APIRouter(prefix="/sessions", tags=["chat"])

class ChatRequest(BaseModel):
    prompt: str

@router.post("/{session_id}/chat")
async def chat_stream(session_id: UUID, request: ChatRequest):
    async def event_generator():
        # SSE format: "data: <content>\n\n"
        yield "data: {\"event\": \"planning\", \"message\": \"Initiating MCTS agent loop...\"}\n\n"
        await asyncio.sleep(0.1)
        yield "data: {\"event\": \"executing\", \"message\": \"Running simulation...\"}\n\n"
        await asyncio.sleep(0.1)
        yield "data: {\"event\": \"completed\", \"message\": \"Task executed successfully. Result: 42\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
