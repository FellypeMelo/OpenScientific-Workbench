"""Manuscript compilation route (RF-008).

Compiles LaTeX source to a PDF via the Tectonic adapter. A missing tectonic
binary is surfaced as 503 (the capability is unavailable in this environment),
and a compilation failure as 422 (the submitted LaTeX is invalid).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from src.infrastructure.latex.tectonic_compiler import TectonicCompiler, TectonicNotAvailableError

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
