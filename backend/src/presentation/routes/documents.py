"""Document ingestion route (RAG-MARKER): parse -> chunk -> embed/upsert into
Qdrant, with best-effort LLM-based knowledge-graph triple extraction.

Reuses the filename-sanitization/size-cap guard introduced for
`POST /workspaces/{id}/files` (`domain/services/upload_guard.py`) rather than
reinventing bounded multipart handling here. `path_guard.py`'s containment
check is NOT reused here -- unlike the workspace upload route, this route has
no caller-supplied destination *path* at all (the uploaded bytes are parsed
in memory and never written to a caller-chosen filesystem location), so
there is nothing for a path-traversal guard to validate.
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel

from src.application.use_cases.ingest_document import IngestDocumentUseCase
from src.domain.ports.document_parser import DocumentParserPort
from src.domain.ports.graph_store import GraphStorePort
from src.domain.ports.vector_store import VectorStorePort
from src.domain.services.upload_guard import (
    InvalidUploadFilenameError,
    UploadTooLargeError,
    iter_upload_bounded,
    sanitize_upload_filename,
)
from src.infrastructure.config import settings
from src.infrastructure.llm.model_client_factory import ModelClientFactory
from src.infrastructure.parsing.chunker import chunk_text
from src.presentation.dependencies import (
    get_current_user_id,
    get_document_parser,
    get_graph_store,
    get_vector_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


class IngestResponse(BaseModel):
    document_id: str
    filename: str
    chunks_indexed: int


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_document(
    file: UploadFile,
    # BYOK provider used ONLY for the best-effort graph-triple-extraction
    # enrichment step, same convention as `routes/chat.py`/`routes/tasks.py`.
    # A missing/invalid key degrades to vector-only indexing (see below)
    # rather than blocking ingestion -- the vector-store upsert is this
    # route's primary deliverable, graph enrichment is a bonus.
    provider: str = "deepseek",
    current_user_id: str = Depends(get_current_user_id),
    parser: DocumentParserPort = Depends(get_document_parser),
    vector_store: VectorStorePort = Depends(get_vector_store),
    graph_store: GraphStorePort = Depends(get_graph_store),
) -> IngestResponse:
    try:
        safe_name = sanitize_upload_filename(file.filename, default="document.pdf")
    except InvalidUploadFilenameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    buffer = bytearray()
    try:
        async for chunk in iter_upload_bounded(file, max_bytes):
            buffer.extend(chunk)
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    finally:
        await file.close()

    if not buffer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    try:
        model_provider = ModelClientFactory.get_client(provider)
    except ValueError:
        # Same degrade-gracefully rationale as the module docstring above --
        # log it (an operator may want to know graph enrichment silently
        # didn't happen) but never fail ingestion over it.
        logger.info(
            "No usable BYOK client for provider=%r; ingesting document_id-to-be "
            "without graph-triple extraction.",
            provider,
        )
        model_provider = None

    document_id = str(uuid.uuid4())
    use_case = IngestDocumentUseCase(
        parser=parser,
        chunk_fn=chunk_text,
        vector_store=vector_store,
        graph_store=graph_store,
        model_provider=model_provider,
    )
    try:
        chunks_indexed = await use_case.execute(
            document_id=document_id, pdf_bytes=bytes(buffer), filename=safe_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return IngestResponse(document_id=document_id, filename=safe_name, chunks_indexed=chunks_indexed)
