import json
import logging
from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.infrastructure.llm.model_client_factory import ModelClientFactory
from src.presentation.dependencies import (
    get_current_user_id,
    get_session_repository,
    get_workspace_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["chat"])

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are the OpenScientific Workbench orchestration agent, coordinating an "
    "MCTS-driven scientific pipeline. Respond helpfully and concisely to the "
    "researcher's request."
)


class ChatRequest(BaseModel):
    prompt: str
    # BYOK provider selector consumed by `ModelClientFactory.get_client`.
    # Kept optional with a default so existing callers that only send
    # `{"prompt": ...}` (e.g. the current frontend, see
    # `frontend/src/app/page.tsx`) keep working unchanged.
    provider: str = "deepseek"


def _sse(event: str, message: str) -> str:
    """Serialize a single SSE frame.

    Wire-format decision (documented here since it affects frontend
    compatibility, see report): the mocked implementation this replaces used
    an envelope shaped `{"event": <str>, "message": <str>}`, and
    `frontend/src/app/page.tsx` (lines ~41-91) already parses exactly that
    envelope:
      - it does `JSON.parse(line.slice(6))` on every `data: ` line,
      - it unconditionally does `updated[lastIndex].text = data.message`
        (a full REPLACE of the last agent bubble's text, not an append), and
      - it only special-cases `data.event === "planning"` / `"completed"` to
        drive the mocked MCTS DAG node highlighting.
    Real provider streaming yields incremental *deltas* (a few characters at a
    time), but the frontend replaces (not appends) `text` on every frame,
    so this generator accumulates deltas server-side and re-sends the
    running total as `message` on every frame. This preserves the existing
    envelope/contract exactly (same two keys, same "planning"/"completed"
    event names at the start/end of the stream) while carrying real content
    instead of the 3 hardcoded strings. A future frontend rewrite (Fase 5)
    could switch to append-on-delta for less redundant payload size, but
    that is out of scope here.
    """
    return f"data: {json.dumps({'event': event, 'message': message})}\n\n"


@router.post("/{session_id}/chat")
async def chat_stream(
    session_id: UUID,
    request: ChatRequest,
    current_user_id: str = Depends(get_current_user_id),
    session_repo: SessionRepositoryPort = Depends(get_session_repository),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
):
    # IDOR fix: this route used to stream a chat response for ANY session id
    # without checking the session existed, let alone who owns it -- any
    # authenticated caller could drive (and burn BYOK provider spend against)
    # another user's session merely by guessing/knowing its UUID. Ownership is
    # transitive through the session's workspace (see `routes/sessions.py`'s
    # `get_session` for the identical pattern); a session that doesn't exist,
    # or whose workspace the caller doesn't own, both 404 identically so this
    # route cannot be used as an existence oracle.
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    workspace = await workspace_repo.get_by_id(session.workspace_id)
    if not workspace or str(workspace.owner_id) != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Resolve the BYOK client *before* opening the SSE stream: a missing API
    # key (`ModelClientFactory.get_client` raises `ValueError`) or an unknown
    # provider name becomes a clean HTTP 400 up front, instead of a stream
    # that opens with a 200 and then fails mid-flight.
    try:
        client = ModelClientFactory.get_client(request.provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    async def event_generator() -> AsyncGenerator[str, None]:
        yield _sse("planning", "Initiating MCTS agent loop...")

        accumulated = ""
        try:
            async for delta in client.generate_stream(
                prompt=request.prompt,
                system_instruction=DEFAULT_SYSTEM_INSTRUCTION,
            ):
                if not delta:
                    continue
                accumulated += delta
                yield _sse("executing", accumulated)
        except Exception:
            # A provider-side failure (auth error, network error, malformed
            # response, etc.) must not crash the request mid-stream -- the
            # HTTP status/headers are already committed at this point. Log it
            # server-side and surface a clean SSE error frame instead.
            logger.exception(
                "LLM provider stream failed for session %s (provider=%s)",
                session_id,
                request.provider,
            )
            yield _sse("error", "The model provider stream failed. Please try again.")
            return

        yield _sse("completed", accumulated or "The model returned an empty response.")

    return StreamingResponse(event_generator(), media_type="text/event-stream")
