"""HPC job dispatch/poll routes (RF-006/RNF-003/RNF-008 gap closure).

`POST /sessions/{session_id}/hpc/jobs` compiles and dispatches a job through
`DispatchHPCJobUseCase`, and `GET /sessions/{session_id}/hpc/jobs/{job_id}`
polls its status -- both against whichever `HPCJobDispatcherPort` backend is
configured process-wide (`presentation/dependencies.py::get_hpc_dispatcher`,
`settings.HPC_BACKEND`: "local" by default, "slurm" as the dormant optional
path). Since that backend selection is fixed per-deployment (not per-request),
both routes always resolve to the SAME dispatcher for a given process, so
`poll_status` here always queries the backend a given job was actually
dispatched to -- see `get_hpc_dispatcher`'s docstring.

Protected by the global JWT middleware like every other route (no allowlist
entry), and NOT exempt from the ownership (IDOR) check pattern established in
the Hardening phase: a session's owner is transitive through its workspace
(`domain/entities/agent_session.py` has no direct `owner_id` of its own), so
both handlers below 404 identically for a session that doesn't exist AND one
that exists but belongs to a different authenticated caller -- mirroring
`routes/sessions.py::get_session` / `routes/tasks.py::submit_task_stream`.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.application.use_cases.dispatch_hpc_job import DispatchHPCJobUseCase
from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.vram_checker import VRAMCheckerPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.presentation.dependencies import (
    get_current_user_id,
    get_hpc_dispatcher,
    get_session_repository,
    get_vram_checker,
    get_workspace_repository,
)

router = APIRouter(prefix="/sessions", tags=["hpc"])


class DispatchJobRequest(BaseModel):
    job_name: str
    script_payload: str
    time_limit: str = "01:00:00"
    # VRAM admission check (RNF-008): when set, the request is gated by
    # whether this much VRAM is locally available -- see
    # `DispatchHPCJobUseCase._check_vram_admission`. `None` (default) skips
    # the check entirely.
    required_vram_gb: Optional[float] = None


class DispatchJobResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str


async def _get_owned_session(
    session_id: UUID,
    current_user_id: str,
    session_repo: SessionRepositoryPort,
    workspace_repo: WorkspaceRepositoryPort,
):
    """Shared ownership guard for both routes below -- see module docstring."""
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    workspace = await workspace_repo.get_by_id(session.workspace_id)
    if not workspace or str(workspace.owner_id) != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    return session


@router.post(
    "/{session_id}/hpc/jobs",
    response_model=DispatchJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def dispatch_hpc_job(
    session_id: UUID,
    request: DispatchJobRequest,
    current_user_id: str = Depends(get_current_user_id),
    session_repo: SessionRepositoryPort = Depends(get_session_repository),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
    dispatcher: HPCJobDispatcherPort = Depends(get_hpc_dispatcher),
    vram_checker: VRAMCheckerPort = Depends(get_vram_checker),
) -> DispatchJobResponse:
    await _get_owned_session(session_id, current_user_id, session_repo, workspace_repo)

    use_case = DispatchHPCJobUseCase(
        session_repo=session_repo,
        dispatcher=dispatcher,
        vram_checker=vram_checker,
    )
    try:
        job_id = await use_case.execute(
            session_id=session_id,
            job_name=request.job_name,
            script_payload=request.script_payload,
            time_limit=request.time_limit,
            required_vram_gb=request.required_vram_gb,
        )
    except ValueError as exc:
        # Mirrors the convention elsewhere in this codebase (e.g.
        # `routes/sessions.py`): a domain-level `ValueError` -- an invalid
        # session state transition, or a rejected VRAM admission check when
        # `reject_if_insufficient_vram` is enabled -- maps to 400, not 404/500.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return DispatchJobResponse(job_id=job_id)


@router.get(
    "/{session_id}/hpc/jobs/{job_id}",
    response_model=JobStatusResponse,
)
async def get_hpc_job_status(
    session_id: UUID,
    job_id: str,
    current_user_id: str = Depends(get_current_user_id),
    session_repo: SessionRepositoryPort = Depends(get_session_repository),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
    dispatcher: HPCJobDispatcherPort = Depends(get_hpc_dispatcher),
) -> JobStatusResponse:
    await _get_owned_session(session_id, current_user_id, session_repo, workspace_repo)

    job_status = await dispatcher.poll_status(job_id)
    return JobStatusResponse(job_id=job_id, status=job_status.value)
