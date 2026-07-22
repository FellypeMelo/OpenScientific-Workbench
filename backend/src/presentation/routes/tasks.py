"""Live MCTS-over-DAG task execution route (RF-001/RF-002).

Wires the previously-dead-code ``SubmitTaskUseCase`` / ``MCTSOrchestrator`` /
``NumericReviewer`` / ``PIISanitizer`` stack into an actual HTTP entry point.
Progress is streamed to the client as Server-Sent Events while the actor-critic
loop runs, via an ``asyncio.Queue`` producer/consumer bridge: the orchestrator's
and use case's synchronous progress hooks (see
``domain/services/mcts_orchestrator.py`` / ``application/use_cases/submit_task.py``)
push events onto the queue from inside a background ``asyncio.Task`` that drives
``SubmitTaskUseCase.execute``, while this route's SSE generator drains the queue
and yields one frame per event. `chat.py`'s stream does not need this pattern --
it is already a natural async generator over the model's own token stream --
but the actor-critic loop here has no single generator to iterate: it is driven
by callback hooks fired from deep inside domain code, hence the bridge.

Known, deliberate scope boundary (see ``infrastructure/llm/llm_node_executor.py``):
``NumericReviewer`` only gates a node when it carries BOTH ``output`` AND
``expected``; ``LLMNodeExecutor`` only ever populates ``output``, so in live
traffic today the review step always approves on the first attempt. The
"review" SSE event / review-status strip machinery below is still real and
exercised by tests (via an injected rejecting reviewer) -- it will start
mattering the moment a second, independently-prompted critic call populates
``expected``, which is intentionally out of scope for this wiring phase.

Node execution backend (RF-005): ``TaskRequest.execution_mode`` picks which
``NodeExecutorPort`` simulates each ready DAG node --
``"sandbox"`` (default) actually runs the LLM-planned ``language``/``command``
for each node inside the real sandbox driver (``SandboxNodeExecutor`` +
``BubblewrapSandboxDriver``, see ``infrastructure/sandbox/``) and rewards on
its real exit code; ``"llm"`` instead asks the model to simulate/describe the
step (the original RF-001 wiring, still available for callers that don't need
real execution). The sandbox driver is resolved lazily, AFTER the request
body is parsed and ONLY when ``execution_mode == "sandbox"`` -- not via an
unconditional route-level ``Depends`` -- so an ``"llm"`` request never pays
the cost of (or can be blocked by) sandbox availability, mirroring how the
BYOK client below is resolved before the SSE stream opens.
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Any, Dict, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.application.use_cases.submit_task import SubmitTaskUseCase
from src.domain.entities.dag import DAGNode, DAGSnapshot
from src.domain.entities.review import ReviewVerdict
from src.domain.ports.artifact_repository import ArtifactRepositoryPort
from src.domain.ports.node_executor import NodeExecutorPort
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.domain.services.mcts_orchestrator import MCTSOrchestrator
from src.infrastructure.llm.llm_node_executor import LLMNodeExecutor
from src.infrastructure.llm.llm_task_planner import LLMTaskPlanner
from src.infrastructure.llm.model_client_factory import ModelClientFactory
from src.infrastructure.sandbox.bubblewrap_driver import SandboxUnavailableError
from src.presentation.dependencies import (
    get_artifact_repository,
    get_current_user_id,
    get_mcp_registry,
    get_node_executor,
    get_sandbox_driver,
    get_session_repository,
    get_workspace_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["tasks"])

# Sentinel distinguishing "queue drained, stream is done" from a real event
# tuple -- an ordinary object identity check, no magic string that could ever
# collide with real event data.
_DONE = object()


class TaskRequest(BaseModel):
    task: str
    # BYOK provider selector, same convention as `routes/chat.py`'s ChatRequest.
    provider: str = "deepseek"
    # Which NodeExecutorPort simulates each DAG node -- see module docstring.
    execution_mode: Literal["llm", "sandbox"] = "sandbox"


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"data: {json.dumps({'event': event, **data})}\n\n"


@router.post("/{session_id}/tasks")
async def submit_task_stream(
    session_id: UUID,
    request: TaskRequest,
    current_user_id: str = Depends(get_current_user_id),
    session_repo: SessionRepositoryPort = Depends(get_session_repository),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
    artifact_repo: ArtifactRepositoryPort = Depends(get_artifact_repository),
):
    # IDOR fix, same pattern as `routes/chat.py::chat_stream` /
    # `routes/sessions.py::get_session`: ownership is transitive through the
    # session's workspace, and a session that doesn't exist or isn't owned by
    # the caller 404s identically so this route cannot be used as an existence
    # oracle.
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    workspace = await workspace_repo.get_by_id(session.workspace_id)
    if not workspace or str(workspace.owner_id) != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Resolve the BYOK client *before* opening the SSE stream, same rationale as
    # `chat.py`: a missing API key / unknown provider becomes a clean 400 up
    # front instead of a stream that opens 200 and then fails mid-flight.
    try:
        client = ModelClientFactory.get_client(request.provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Resolve the node executor up front too, same rationale: a sandbox that
    # can't actually provide isolation on this host becomes a clean 503 before
    # the stream opens, never a raw 500 or (worse) a silent unsandboxed
    # fallback. Resolved lazily/conditionally (a plain function call, not a
    # route-level `Depends`) so an `"llm"`-mode request never even attempts to
    # construct a sandbox driver.
    # The MCP tool registry (bio/DB adapters + sandboxed action tools) is
    # resolved regardless of execution_mode, so `LLMTaskPlanner` can list real
    # tool names in the planning prompt either way. Only `SandboxNodeExecutor`
    # actually acts on a `"tool"`-language node (routes it through
    # `MCPRouterPort.route()`, see `_simulate_tool_call`); `LLMNodeExecutor`
    # ignores `node.language`/`node.command` entirely regardless of value (it
    # always just re-prompts the model with `node.description`), so a
    # `"tool"` node under `execution_mode="llm"` still gets a response, just
    # never a real tool call -- a pre-existing limitation of that executor,
    # not new here.
    mcp_registry = get_mcp_registry()
    tool_names = list(getattr(mcp_registry, "registry", {}).keys())

    executor: NodeExecutorPort
    if request.execution_mode == "sandbox":
        try:
            executor = get_node_executor(get_sandbox_driver(), mcp_registry)
        except SandboxUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
    else:
        executor = LLMNodeExecutor(client)

    queue: "asyncio.Queue[object]" = asyncio.Queue()

    def _emit(event: str, **data: Any) -> None:
        queue.put_nowait((event, data))

    def _on_plan(snapshot: DAGSnapshot) -> None:
        _emit("dag_planned", **snapshot.to_dict())

    def _on_node_start(node: DAGNode) -> None:
        _emit("node_start", node=node.model_dump())

    def _on_node_update(node: DAGNode) -> None:
        _emit("node_update", node=node.model_dump())

    def _on_review(verdict: ReviewVerdict, attempt: int, max_attempts: int) -> None:
        _emit(
            "review",
            approved=verdict.approved,
            reason=verdict.reason,
            attempt=attempt,
            max_attempts=max_attempts,
        )

    orchestrator = MCTSOrchestrator(
        planner=LLMTaskPlanner(client, tool_names=tool_names),
        executor=executor,
        on_plan=_on_plan,
        on_node_start=_on_node_start,
        on_node_update=_on_node_update,
    )
    use_case = SubmitTaskUseCase(
        session_repo=session_repo,
        orchestrator=orchestrator,
        on_review=_on_review,
        artifact_repo=artifact_repo,
    )

    async def _run() -> None:
        try:
            updated = await use_case.execute(session_id=session_id, task_nl=request.task)
            _emit(
                "completed",
                session_status=updated.session_status,
                dag_snapshot=updated.dag_snapshot,
                dag_generation_attempts=updated.dag_generation_attempts,
            )
        except Exception as exc:
            # Mirrors `chat.py`: the HTTP status/headers are already committed
            # by the time this runs (the SSE stream is open), so a failure here
            # must surface as a clean SSE error frame, never a crashed request.
            logger.exception("Task execution failed for session %s", session_id)
            _emit("error", message=str(exc))
        finally:
            queue.put_nowait(_DONE)

    async def event_generator() -> AsyncGenerator[str, None]:
        runner = asyncio.create_task(_run())
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                event, data = item  # type: ignore[misc]
                yield _sse(event, data)
        finally:
            # Make sure the background task is fully awaited (and its exceptions
            # surfaced to the server log via the try/except above, not left as
            # an "exception never retrieved" warning) before the generator, and
            # therefore the HTTP response, closes.
            await runner

    return StreamingResponse(event_generator(), media_type="text/event-stream")
