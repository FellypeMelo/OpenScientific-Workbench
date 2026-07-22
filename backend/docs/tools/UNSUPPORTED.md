# Unsupported tools (Tier D)

These tools are registered in the MCP catalog with the correct name/schema (so they show up when
listing available tools, and `LLMTaskPlanner` never hallucinates a plausible-sounding name that
silently doesn't exist), but their handler raises
`infrastructure.tools._sandbox_tool_base.NotSupportedError` (a `NotImplementedError` subclass)
instead of computing a result. **This is deliberate, not a bug to "fix" by faking a result.**

A biomedical AI agent returning a fabricated number from an untrained model (e.g. a made-up docking
score, a made-up drug-repurposing rank) is actively dangerous — a real researcher could act on it.
Every entry below needs either a proprietary/huge pretrained checkpoint this single-local-server
deployment cannot obtain or train from scratch, or a GPU cluster it does not have.

| Tool | Why unsupported | What would be needed to support it |
|---|---|---|
| `get_uce_embeddings_scRNA` | Universal Cell Embeddings requires a large pretrained foundation-model checkpoint + GPU. Biomni's own paper marks this "not currently supported in the web UI" for the same reason. | The published UCE checkpoint (multi-GB) + a CUDA GPU host. |
| `map_to_ima_interpret_scRNA` | Downstream of UCE embeddings above — same GPU/checkpoint dependency. | Same as `get_uce_embeddings_scRNA`. |
| `run_diffdock_with_smiles` | DiffDock is a diffusion model for docking pose generation, needs its own pretrained checkpoint + GPU + its own Docker container per Biomni's own tool description. | DiffDock checkpoint + GPU + a way to run its container from inside this project's single-container/Compose deployment (not currently architected for nested containers). |
| `retrieve_topk_repurposing_drugs_from_disease_txgnn` | TxGNN is a trained graph neural network over a specific knowledge graph snapshot; there is no publicly redistributable pretrained checkpoint bundled with this project, and training one from scratch is a research project of its own, not a packaging task. | A trained TxGNN checkpoint + the exact knowledge graph it was trained against. |

## Partially supported (documented, not Tier D)

- `predict_admet_properties`, `predict_binding_affinity_protein_1d_sequence` — both use
  DeepPurpose, which downloads its own pretrained weights from its model zoo on first use rather
  than requiring a bundled checkpoint. Registered as real (Tier B) tools, but the FIRST call from a
  fresh deployment will be slow (weight download) and requires outbound network access despite the
  rest of the sandbox defaulting to `--unshare-net` — this specific tool's script needs
  `allow_network=True` on the sandbox call. Document this clearly in the tool's own docstring so an
  operator isn't surprised by an outbound connection from an otherwise network-isolated sandbox.

## If you are implementing a new tool and it turns out to belong here

1. Implement the handler to raise `NotSupportedError("<what's missing>; see backend/docs/tools/UNSUPPORTED.md")`.
2. Add a row to the table above (tool name, why, what's needed).
3. Still register it in the MCP catalog (name + schema) — don't just omit it. A registered-but-honestly-refusing
   tool is different from a tool that doesn't exist; the planner should be able to tell the difference
   rather than silently never knowing the capability was ever considered.
