"""Real manuscript critique (RF-008 gap closure).

Replaces the frontend's hardcoded `DEFAULT_COMMENTS` demo array
(`frontend/src/components/ManuscriptEditor.tsx`) with an actual review: the
manuscript's LaTeX source is sent to a BYOK LLM (any `ModelProviderPort`,
same "drive the existing, already-tested port with a structured-JSON prompt"
choice as `infrastructure/llm/llm_task_planner.py`'s DAG planner and
`ingest_document.py`'s triple extraction -- KISS, no extra runtime) and asked
for concrete, targeted corrections.

Only depends on domain ports/services, per this codebase's Clean Architecture
layering (application depends only on domain, never infrastructure) --
`presentation/routes/manuscript.py` wires the concrete `ModelProviderPort` in
at construction time, exactly like `chat.py`/`tasks.py` already do for their
own BYOK clients.
"""
import logging
from typing import List

from src.domain.entities.manuscript import CriticComment
from src.domain.ports.model_provider import ModelProviderPort
from src.domain.services.json_extraction import extract_json

logger = logging.getLogger(__name__)

_CRITIQUE_SYSTEM_INSTRUCTION = (
    "You are a meticulous scientific manuscript critic reviewing LaTeX source. "
    "Identify concrete, actionable issues ONLY: spelling/grammar errors, "
    "numeric precision or unit inconsistencies (e.g. a claimed value whose "
    "precision does not match its stated tolerance), and factual claims that "
    "contradict other parts of the same document. Do NOT invent issues that "
    "are not actually present. For each issue, quote the EXACT, verbatim "
    "substring from the source that should change as `target_text` (it MUST "
    "appear character-for-character in the source) and the exact replacement "
    "text as `suggestion`. Respond with ONLY a JSON object of the form "
    '{"comments": [{"target_text": "...", "suggestion": "..."}]}. If the '
    'manuscript has no issues, respond with {"comments": []}. Do not include '
    "any prose outside the JSON."
)

# Caps how much LaTeX source is sent to the critic LLM per call, keeping a
# single request's token/cost bounded regardless of manuscript length --
# mirrors `ingest_document.py`'s `_MAX_EXTRACTION_CHARS` cap for the same
# reason.
_MAX_SOURCE_CHARS = 12000


class CritiqueManuscriptUseCase:
    def __init__(self, model_provider: ModelProviderPort):
        self.model_provider = model_provider

    async def execute(self, latex_source: str) -> List[CriticComment]:
        """Returns the critic's comments for ``latex_source``, or an empty
        list for empty/whitespace-only input (nothing to critique).

        Raises ``ValueError`` when the model's response could not be parsed
        into the expected shape -- a genuine "the critic failed to produce a
        usable answer" outcome the caller (route) should surface as a clean
        502, not silently swallow into a fake empty-comments success.
        """
        if not latex_source or not latex_source.strip():
            return []

        raw = await self.model_provider.generate_response(
            prompt=latex_source[:_MAX_SOURCE_CHARS],
            system_instruction=_CRITIQUE_SYSTEM_INSTRUCTION,
            temperature=0.0,
        )
        try:
            payload = extract_json(raw)
        except ValueError as exc:
            raise ValueError("Critic response contained no parseable JSON.") from exc

        raw_comments = payload.get("comments") if isinstance(payload, dict) else None
        if not isinstance(raw_comments, list):
            raise ValueError("Critic response's `comments` field was missing or not a list.")

        comments: List[CriticComment] = []
        for i, item in enumerate(raw_comments):
            if not isinstance(item, dict):
                continue
            target_text = item.get("target_text")
            suggestion = item.get("suggestion")
            if not isinstance(target_text, str) or not isinstance(suggestion, str):
                continue
            if not target_text or target_text not in latex_source:
                # Discard hallucinated/paraphrased quotes that do not occur
                # verbatim in the source: `ManuscriptDocument.apply_correction`
                # requires an exact substring match too, and the frontend's
                # "Aplicar correção" button would silently do nothing for a
                # comment whose `targetText` can never be found.
                logger.warning(
                    "Discarding critic comment whose target_text is not a "
                    "literal substring of the manuscript source."
                )
                continue
            comments.append(
                CriticComment(id=f"c{i + 1}", target_text=target_text, suggestion=suggestion)
            )
        return comments
