"""Manuscript compilation + critique routes (RF-008).

``/compile`` compiles LaTeX source to a PDF via the Tectonic adapter. A missing
tectonic binary is surfaced as 503 (the capability is unavailable in this
environment), and a compilation failure as 422 (the submitted LaTeX is
invalid).

``/critique`` replaces the frontend's previous hardcoded `DEFAULT_COMMENTS`
demo array (see `frontend/src/components/ManuscriptEditor.tsx`) with a real
BYOK-LLM-backed review, via `CritiqueManuscriptUseCase`. Not additionally
gated behind `get_current_user_id` -- mirrors `/compile` above and
`routes/mcp.py`'s module docstring rationale: this route has no per-user owned
resource to check, it is still fully covered by the global JWT middleware.
"""
import logging
from typing import List

import httpx
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import Response
from pydantic import BaseModel

from src.application.use_cases.critique_manuscript import CritiqueManuscriptUseCase
from src.domain.entities.manuscript import CriticComment
from src.infrastructure.latex.tectonic_compiler import TectonicCompiler, TectonicNotAvailableError
from src.infrastructure.llm.model_client_factory import ModelClientFactory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manuscript", tags=["manuscript"])


def get_tectonic_compiler() -> TectonicCompiler:
    return TectonicCompiler()


class CompileRequest(BaseModel):
    latex_source: str


# Declared as a sync `def` so FastAPI runs the blocking tectonic subprocess in a
# threadpool instead of on the event loop.
@router.post("/compile")
def compile_manuscript(
    request: CompileRequest,
    compiler: TectonicCompiler = Depends(get_tectonic_compiler),
) -> Response:
    try:
        pdf_bytes = compiler.compile(request.latex_source)
    except TectonicNotAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RuntimeError as exc:
        # 422 (unprocessable): the submitted LaTeX could not be compiled.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(content=pdf_bytes, media_type="application/pdf")


class CritiqueRequest(BaseModel):
    latex_source: str
    # BYOK provider selector, same convention as `routes/chat.py`'s ChatRequest
    # and `routes/tasks.py`'s TaskRequest.
    provider: str = "deepseek"


class CritiqueResponse(BaseModel):
    comments: List[CriticComment]


@router.post("/critique", response_model=CritiqueResponse)
async def critique_manuscript(request: CritiqueRequest) -> CritiqueResponse:
    # Resolve the BYOK client up front: a missing API key / unknown provider
    # becomes a clean 400, same rationale as `chat.py`/`tasks.py`.
    try:
        client = ModelClientFactory.get_client(request.provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        comments = await CritiqueManuscriptUseCase(client).execute(request.latex_source)
    except ValueError as exc:
        # The critic responded but not in a usable shape -- a genuine upstream
        # failure (mirrors `routes/mcp.py`'s BioAPIError -> 502 mapping), not a
        # malformed request from this caller.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.exception("Manuscript critique provider call failed (provider=%s)", request.provider)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The critic model provider failed to respond.",
        ) from exc

    return CritiqueResponse(comments=comments)
