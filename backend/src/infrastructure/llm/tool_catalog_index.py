"""Semantic retrieval over the registered tool catalog for `LLMTaskPlanner`.

Closes the "KNOWN SCALING LIMIT" flagged in `llm_task_planner.py`: dumping
every registered tool name into every planning prompt is fine at dozens of
tools, but wasteful and relevance-diluting once the catalog reaches the full
~172-tool size (see `backend/docs/tools/`). When real Qdrant infra is
configured, this indexes each registered tool's name+description (parsed from
`backend/docs/tools/db_adapter_catalog.md` and `action_tool_catalog.md`) into
its own collection and returns the top-K most relevant tools for a given task
-- exactly the Biomni paper's "prompt-based retriever" step, reusing the same
`QdrantVectorStore` adapter/FastEmbed pattern `infrastructure/vector/qdrant_client.py`
already established for RAG document chunks (a *separate* collection, so tool
entries never mix with ingested document chunks).

`QdrantVectorStore.search()` in mock mode (`enabled=False`, e.g. no live
Qdrant / CI) returns synthetic `"[mock retrieval chunk ...]"` placeholder
text, not real tool names -- feeding that into a planning prompt as if it were
a real tool would be actively wrong, not just degraded. `ToolCatalogIndex.usable`
mirrors the store's own `enabled` flag so callers (here, `LLMTaskPlanner`) can
detect this and fall back to the full-catalog-dump behavior instead.
"""
import re
from pathlib import Path
from typing import Dict, List, Tuple

from src.infrastructure.vector.qdrant_client import QdrantVectorStore

# backend/src/infrastructure/llm/tool_catalog_index.py -> parents[3] == backend/
_CATALOG_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs" / "tools"
_CATALOG_FILENAMES = ("db_adapter_catalog.md", "action_tool_catalog.md")

# Matches catalog markdown entries of the form:
#   - **tool_name** — one-line description.
#   - **tool_name**(param: type, ...) — one-line description.
# (both `db_adapter_catalog.md` and `action_tool_catalog.md` use this exact
# `- **name**...— description` shape; see either file's own module docstring
# for the source-of-truth this was transcribed from). The signature group
# allows ONE level of nested parens -- e.g. `time_span: tuple = (0,24)` --
# since a plain `[^)]*` closes on the tuple's own `)` before the arg list's
# own closing paren, silently dropping the whole entry (and its description)
# for any tool whose signature has a parenthesized default value.
_ENTRY_RE = re.compile(
    r"^- \*\*([A-Za-z0-9_]+)\*\*(?:\((?:[^()]|\([^()]*\))*\))?\s+—\s+(.+)$", re.MULTILINE
)

# Separator between name and description in the indexed text. Deliberately
# not a substring either half could plausibly contain (tool names are
# `[A-Za-z0-9_]+`, descriptions are prose), so splitting back out on retrieval
# is unambiguous.
_NAME_DESCRIPTION_SEP = "::"


def parse_tool_descriptions(*catalog_texts: str) -> Dict[str, str]:
    """Extracts `{tool_name: description}` from one or more catalog markdown
    texts. Unknown/unparseable lines are silently skipped -- this is a
    best-effort retrieval aid, not a schema validator (that's Pydantic's job
    on each tool's actual argument model)."""
    descriptions: Dict[str, str] = {}
    for text in catalog_texts:
        for match in _ENTRY_RE.finditer(text):
            name, description = match.group(1), match.group(2).strip()
            descriptions.setdefault(name, description)
    return descriptions


def load_catalog_descriptions() -> Dict[str, str]:
    """Reads `parse_tool_descriptions()` off the real catalog docs on disk
    (`backend/docs/tools/{db_adapter,action_tool}_catalog.md`). Returns `{}`,
    rather than raising, when a file is missing -- `backend/Dockerfile`'s
    runtime stage does not `COPY docs/` into the image (only `src/`), so this
    is the normal, expected outcome in production, not an error: retrieval
    still works, it just indexes tool names without prose descriptions."""
    texts = []
    for filename in _CATALOG_FILENAMES:
        path = _CATALOG_DOCS_DIR / filename
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return parse_tool_descriptions(*texts)


class ToolCatalogIndex:
    """Wraps a `QdrantVectorStore` to index and retrieve tool name/description
    pairs. Construct with a store pointed at a dedicated collection (NOT the
    RAG document collection)."""

    def __init__(self, store: QdrantVectorStore):
        self._store = store
        self._indexed = False

    @property
    def usable(self) -> bool:
        return self._store.enabled

    async def ensure_indexed(self, tool_names: List[str], descriptions: Dict[str, str]) -> None:
        """Upserts one point per tool name. Idempotent within a process
        (skips after the first successful call) -- call again after the
        registry changes shape (e.g. in a test) by constructing a fresh
        `ToolCatalogIndex` rather than fighting this cache."""
        if self._indexed or not self.usable or not tool_names:
            return
        chunks = [
            {
                "id": name,
                "text": f"{name}{_NAME_DESCRIPTION_SEP}{descriptions.get(name, name)}",
            }
            for name in tool_names
        ]
        await self._store.upsert(chunks)
        self._indexed = True

    async def top_k(self, task_nl: str, k: int) -> List[Tuple[str, str]]:
        """Returns up to `k` `(tool_name, description)` pairs most relevant to
        `task_nl`. Empty list when the store is in mock mode -- see this
        class's docstring."""
        if not self.usable:
            return []
        results = await self._store.search(task_nl, top_k=k)
        pairs = []
        for text in results:
            name, sep, description = text.partition(_NAME_DESCRIPTION_SEP)
            if sep and name:
                pairs.append((name, description))
        return pairs

    async def close(self) -> None:
        """Releases the underlying store's real client connection pool, if
        one was ever created. Wired into `presentation/main.py`'s `lifespan`
        shutdown via `presentation/dependencies.py::close_tool_catalog_index`."""
        await self._store.close()
