"""Best-effort JSON extraction from free-form LLM text responses.

Shared by any use case/adapter that asks an LLM (`ModelProviderPort`) for a
strict-JSON answer but must tolerate prose/markdown fences wrapped around it
-- originally lived only in `infrastructure/llm/llm_task_planner.py`
(RF-001's DAG planner); factored out here (a pure domain service, zero infra
imports) so `application/use_cases/ingest_document.py`'s best-effort
triple-extraction step (RAG-MARKER) can reuse the exact same parsing without
an application-layer module importing from `infrastructure/` (this
codebase's Clean Architecture layering forbids that -- application depends
only on domain ports/services).
"""
import json
from typing import Any


def extract_json(text: str) -> Any:
    """Best-effort extraction of the first JSON object/array in an LLM response.

    Tolerates prose and ```json fences around the payload; raises ValueError
    when nothing parseable is found so callers get a clear signal.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try the container that OPENS earliest in the text first, so a top-level
    # array `[{...}]` is not mistaken for its inner object `{...}`.
    candidates = []
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            candidates.append((start, text[start : end + 1]))

    for _, candidate in sorted(candidates, key=lambda c: c[0]):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError("Response contained no parseable JSON.")
