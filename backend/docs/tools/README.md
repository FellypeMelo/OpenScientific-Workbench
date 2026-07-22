# OSW scientific tool catalog

OpenScientific-Workbench's Biomni-style "action space": real callable tools the MCTS/DAG
orchestrator (and any direct `POST /api/v1/mcp/tools/call` caller) can reach, wired into
`presentation/dependencies.py::get_mcp_registry()`.

## Status

172 registered tools as of this writing:

| Layer | Count | Where | Execution |
|---|---|---|---|
| Bio/DB/network adapters | 41 | `backend/src/infrastructure/mcp/*.py` | In-process `httpx` calls, no sandbox (pure network I/O) |
| Sandboxed action tools | 131 | `backend/src/infrastructure/tools/*.py` | Always inside the `bwrap` jail via `run_in_sandbox()` |

Run this to see the live count and full name list on any checkout:

```bash
cd backend
SANDBOX_RUNTIME=mock .venv/Scripts/python.exe -c "from src.presentation.dependencies import get_mcp_registry; r = get_mcp_registry(); print(len(r.registry)); print(sorted(r.registry.keys()))"
```

(`SANDBOX_RUNTIME=mock` is only needed to see the action-tool count on a host without a real
`bwrap` binary, e.g. this project's Windows dev machine -- with no working sandbox, `get_mcp_registry()`
degrades to registering only the 41 network tools, see that function's own docstring.)

## The 4 catalog documents

- **[`db_adapter_catalog.md`](./db_adapter_catalog.md)** -- the spec every `infrastructure/mcp/*.py`
  DB/network adapter was implemented against: tool name, one-line description, which domain group it
  belongs to.
- **[`action_tool_catalog.md`](./action_tool_catalog.md)** -- the spec every
  `infrastructure/tools/*.py` sandboxed action tool was implemented against: exact required/optional
  parameters with types and defaults, plus a Tier A/B/C/D hint per tool (see "Tiering" below).
- **[`UNSUPPORTED.md`](./UNSUPPORTED.md)** -- the Tier D registry: tools that are registered (correct
  name/schema) but whose handler always raises `NotSupportedError` because they need a
  proprietary/huge pretrained checkpoint or a GPU cluster this single-local-server deployment doesn't
  have. Read this before assuming a registered tool actually computes something.
- **[`data_lake_source_list.md`](./data_lake_source_list.md)** -- raw input for
  `../../../data_lake/MANIFEST.md` (the ~48 bundled reference datasets some action tools read from
  `/datalake`, e.g. MSigDB gene sets, GWAS Catalog, BioGRID interaction tables). Not the same thing as
  the DB/network adapters above -- those are live API calls, this is static local reference data.

## Tiering (why some tools are more trustworthy than others)

Every action tool is one of:

- **A** -- deterministic library call (biopython, RDKit, `cobra`, ...), no statistical model involved.
- **B** -- real numerical method (scipy curve-fitting, an ODE integrator, a closed-form formula like
  MIRD dosimetry) -- correctness depends on the input data, not on a black-box model.
- **C** -- general-purpose image-processing pipeline (scikit-image/opencv/trackpy thresholding,
  segmentation, tracking) -- real code, but NOT validated against a specific published
  method/clinical protocol. Treat results as a starting point, not a diagnosis.
- **D** -- registered but unsupported (see `UNSUPPORTED.md`) -- always raises, never fabricates a
  result.

This tiering exists because a biomedical AI tool that silently returns a plausible-looking but
made-up number (an untrained model's "docking score", a hallucinated drug-repurposing rank) is
actively dangerous. If you are extending this catalog, pick a tier honestly before writing a single
line of the handler -- see `action_tool_catalog.md`'s own tiering rules for the exact criteria.

## Testing reality (read before writing a test for a new tool)

`backend/src/infrastructure/tools/_sandbox_tool_base.py`'s module docstring is the authoritative
explanation, but the short version: the `script_body` strings inside `infrastructure/tools/*.py`
import scipy/biopython/RDKit/etc, which only exist in the **sandbox toolkit's own conda env**
(`backend/sandbox/environment.yml`), never in this repo's own `backend/.venv` that `pytest` runs
under. This repo's fast unit test suite can therefore only verify the **wiring/validation layer**
(Pydantic argument validation, correct args round-trip via `FakeSandboxDriver`, correct Tier D
`NotSupportedError`) -- never a `script_body`'s real scientific correctness. That can only be checked
by actually building the sandbox-toolkit Docker image and calling the tool for real (see
"Verifying a rebuilt sandbox image" below). This mirrors how `test_bubblewrap_driver.py` itself only
ever mocks `subprocess.run` -- real bwrap isolation is proven separately, in
`tests/integration/test_bubblewrap_sandbox_escape.py`, which needs a real Linux host.

## Adding a new tool

1. Add its spec (name, params, tier) to `action_tool_catalog.md` (or `db_adapter_catalog.md` if it's
   a live network call, not sandboxed computation).
2. Implement it in the matching `infrastructure/tools/<category>.py` (or a new
   `infrastructure/mcp/<domain>_db_adapters.py` file for a network adapter), following the existing
   files in that directory as the pattern reference.
3. Register it in that file's `register_<name>_tools(...)` function.
4. Wire the registration call into `presentation/dependencies.py::get_mcp_registry()` if it's a new
   file (an existing file's new tool is already covered by that file's existing registration call).
5. Write a test using `FakeSandboxDriver` (action tools) or `httpx.MockTransport` (DB adapters) --
   see any existing `tests/unit/test_<name>.py` for the pattern.
6. If the tool needs a new conda/pip package for the sandbox toolkit, add it to
   `backend/sandbox/environment.yml` or `requirements-pip.txt` -- and note in your PR that the image
   has not been rebuilt/re-verified against the new package name (see the next section).

## Verifying a rebuilt sandbox image

`backend/sandbox/environment.yml` has never been solved/built in this project's Windows dev
environment (no Linux host with `conda`/`micromamba` available here). The first real verification
step for ANY environment.yml/requirements-pip.txt change is:

```bash
docker compose build backend
```

If the conda solver rejects a package name, check https://bioconda.github.io/recipes.html (or
`conda search -c bioconda <name>`) for the correct one and fix it in `environment.yml`. Once the
image builds, a real end-to-end tool call (`SANDBOX_RUNTIME=bubblewrap docker compose up`, then
`POST /api/v1/mcp/tools/call` with a Tier A/B tool and a known-answer input, e.g. `pcr_simple` with
the primers/sequence from `action_tool_catalog.md`'s own examples) is the real scientific-correctness
check this repo's unit tests structurally cannot perform.
