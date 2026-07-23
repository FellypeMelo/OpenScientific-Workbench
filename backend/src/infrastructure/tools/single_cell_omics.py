"""Single-cell / omics / regulatory genomics action tools (Fase 5).

Implements every tool listed under "## Categoria: Single-cell / omics /
regulatory genomics" in `backend/docs/tools/action_tool_catalog.md`. Follows
the conventions set by `_sandbox_tool_base.py` (every Tier A/B/C tool runs
its real script INSIDE the bwrap sandbox via `run_in_sandbox`, Tier D tools
raise `NotSupportedError` directly) and `infrastructure/mcp/bio_direct_adapters.py`
(module exposes `register_single_cell_omics_tools(registry, driver) -> List[str]`).

Design notes that apply across most tools below:

- **Path arguments.** Every argument that names a file/dir the sandboxed
  script reads is validated with `ensure_safe_relative_path`
  (`domain/services/path_guard.py`) and referenced inside the script as
  `f"/workspace/{validated}"` -- `BubblewrapSandboxDriver` binds the caller's
  workspace at `/workspace` (see that driver's module docstring). The one
  exception is `annotate_celltype_scRNA`'s `DATA_LAKE` argument, which points
  at the sandbox's fixed, read-only data-lake mount (`/datalake`, see
  `settings.DATA_LAKE_ROOT`) rather than the per-call workspace -- it is
  validated separately (`_validate_data_lake_dir`) to only ever resolve
  inside that mount, never an arbitrary absolute path.

- **Outputs and `/workspace` being read-only.** `BubblewrapSandboxDriver`
  binds `/workspace` READ-ONLY inside the jail (see its module docstring) --
  a sandboxed script can never write a result file back into the caller's
  workspace. Every tool below that would normally take an `output_dir`/
  `output_prefix`/`output_name`/`output_file` argument therefore does any
  CLI/library-required scratch writes under the sandbox's own writable
  `/tmp` (via `tempfile.mkdtemp`) and returns the actually computed results
  (counts, tables, small file contents) inline in its JSON result, rather
  than a path that stops existing the moment the sandboxed process exits.
  The user-supplied output-location argument is still validated and echoed
  back as a label for readability, not a real host-visible location.

- **Tools that need outbound network access.** `get_rna_seq_archs4`,
  `get_gene_set_enrichment_analysis_supported_database_list` and
  `gene_set_enrichment_analysis` call real external APIs (ARCHS4 via `gget`,
  Enrichr via `gget`/`gseapy`) that have no viable fully-offline substitute
  bundled with this project. Like `predict_admet_properties` (see
  `backend/docs/tools/UNSUPPORTED.md`'s "Partially supported" section),
  these need a sandbox driver constructed with `allow_network=True` to
  actually succeed; with the default network-isolated driver they fail loud
  with a real connection error (never a fabricated result).

- **`annotate_celltype_scRNA` is a genuine Tier A/B hybrid.** The clustering
  and marker-gene identification (real `scanpy` Leiden clustering +
  Wilcoxon rank-sum test) run inside the sandbox like everything else. Cell
  type *naming* from those marker genes is delegated to a real LLM call --
  but that call happens in THIS trusted process (never inside the sandbox,
  which has no access to API keys or app secrets) via OSW's own BYOK
  `ModelProviderPort`/`ModelClientFactory`, exactly like every other
  LLM-calling route in this app (`routes/tasks.py`, `routes/manuscript.py`,
  ...) -- the caller picks a provider (`llm` argument), never a hardcoded
  model id.
"""
import posixpath
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.domain.ports.model_provider import ModelProviderPort
from src.domain.services.path_guard import PathTraversalError, ensure_safe_relative_path
from src.infrastructure.llm.model_client_factory import ModelClientFactory
from src.infrastructure.tools._sandbox_tool_base import NotSupportedError, run_in_sandbox

#: Fixed, read-only data-lake mount inside the bwrap jail (see
#: `BubblewrapSandboxDriver`'s module docstring / `settings.DATA_LAKE_ROOT`).
DATA_LAKE_MOUNT = "/datalake"

_SUPPORTED_LLM_PROVIDERS = {"deepseek", "glm", "z.ai", "zhipu", "claude", "anthropic", "openai"}


# --------------------------------------------------------------------------
# Shared path-validation helpers (wrap `ensure_safe_relative_path` so every
# Pydantic model below gets a consistent ValueError message on traversal).
# --------------------------------------------------------------------------

def _validate_path(value: Any) -> str:
    try:
        return ensure_safe_relative_path(value)
    except PathTraversalError as exc:
        raise ValueError(str(exc)) from exc


def _validate_optional_path(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    return _validate_path(value)


def _validate_paths(values: List[Any]) -> List[str]:
    return [_validate_path(v) for v in values]


def _validate_data_lake_dir(value: Any) -> str:
    text = str(value).strip().replace("\\", "/").rstrip("/")
    if text == DATA_LAKE_MOUNT or text.startswith(DATA_LAKE_MOUNT + "/"):
        return text
    raise ValueError(
        f"DATA_LAKE must be the sandbox's read-only data lake mount "
        f"({DATA_LAKE_MOUNT}) or a subdirectory of it, not {value!r} -- see "
        "BubblewrapSandboxDriver's module docstring for the fixed /datalake bind."
    )


def _validate_relative_pair(data_dir: str, filename: str) -> None:
    """Validates that `data_dir/filename` (as a single joined relative path)
    never escapes the workspace, even if each half looks safe alone."""
    _validate_path(posixpath.join(data_dir, filename))


# ==========================================================================
# annotate_celltype_scRNA (Tier A/B hybrid)
# ==========================================================================

class AnnotateCelltypeScrnaArgs(BaseModel):
    adata_filename: str
    data_dir: str
    data_info: str
    cluster: str = "leiden"
    # BYOK provider name consumed by `ModelClientFactory.get_client` -- NOT a
    # raw model id (Biomni's own default, "claude-3-5-sonnet-20241022", is a
    # hardcoded model string; OSW is BYOK, so the caller picks a *provider*
    # and OSW's own client resolves the concrete model version).
    llm: str = "anthropic"
    composition: Optional[List[Dict[str, Any]]] = None
    DATA_LAKE: str = DATA_LAKE_MOUNT

    @model_validator(mode="after")
    def _check_adata_path(self) -> "AnnotateCelltypeScrnaArgs":
        _validate_relative_pair(self.data_dir, self.adata_filename)
        return self

    @field_validator("llm")
    @classmethod
    def _check_llm_provider(cls, value: str) -> str:
        if value.strip().lower() not in _SUPPORTED_LLM_PROVIDERS:
            raise ValueError(
                f"Unsupported llm provider {value!r}; expected one of "
                f"{sorted(_SUPPORTED_LLM_PROVIDERS)} (see ModelClientFactory)."
            )
        return value

    @field_validator("DATA_LAKE")
    @classmethod
    def _check_data_lake(cls, value: str) -> str:
        return _validate_data_lake_dir(value)


_SCRIPT_ANNOTATE_CELLTYPE_SCRNA = """
import os as _os
import scanpy as _sc

_rel = _os.path.join(_args['data_dir'], _args['adata_filename'])
_adata = _sc.read_h5ad(f"/workspace/{_rel}")
_cluster_key = _args['cluster']

if _cluster_key not in _adata.obs.columns:
    _sc.pp.normalize_total(_adata, target_sum=1e4)
    _sc.pp.log1p(_adata)
    _sc.pp.highly_variable_genes(_adata, n_top_genes=min(2000, _adata.n_vars))
    _adata = _adata[:, _adata.var['highly_variable']].copy()
    _sc.pp.scale(_adata, max_value=10)
    _n_comps = max(1, min(50, _adata.n_obs - 1, _adata.n_vars - 1))
    _sc.tl.pca(_adata, n_comps=_n_comps)
    _sc.pp.neighbors(_adata)
    _sc.tl.leiden(_adata, key_added=_cluster_key)

_sc.tl.rank_genes_groups(_adata, _cluster_key, method='wilcoxon', n_genes=15)
_clusters = {}
for _grp in sorted(_adata.obs[_cluster_key].astype(str).unique().tolist()):
    _top = [str(_g) for _g in _adata.uns['rank_genes_groups']['names'][_grp][:10]]
    _n = int((_adata.obs[_cluster_key].astype(str) == _grp).sum())
    _clusters[_grp] = {"top_genes": _top, "n_cells": _n}

_ontology = []
_ontology_csv = _args['DATA_LAKE'] + '/czi_census_datasets_v4.csv'
if _os.path.exists(_ontology_csv):
    import csv as _csv
    _seen = set()
    with open(_ontology_csv, encoding='utf-8') as _fh:
        for _row in _csv.DictReader(_fh):
            for _ct in str(_row.get('cell_type') or '').split(';'):
                _ct = _ct.strip()
                if _ct:
                    _seen.add(_ct)
    _ontology = sorted(_seen)[:300]

print(_json.dumps({"clusters": _clusters, "ontology_candidates": _ontology}))
""".strip()

_ANNOTATION_SYSTEM_INSTRUCTION = (
    "You are an expert single-cell biologist. Given a list of differentially "
    "expressed marker genes for one cluster of a scRNA-seq dataset, name the "
    "single most likely cell type. Respond with EXACTLY the format "
    "'<cell type>; <confidence 0-1>; <one-sentence reason>' and nothing else."
)


def _composition_context(composition: Optional[List[Dict[str, Any]]], cluster_id: str) -> Optional[str]:
    if not composition:
        return None
    for record in composition:
        key = str(record.get("cluster") if "cluster" in record else record.get("cluster_id"))
        if key == cluster_id:
            proportions = {k: v for k, v in record.items() if k not in ("cluster", "cluster_id")}
            return "; ".join(f"{k}:{v}" for k, v in proportions.items())
    return None


async def annotate_celltype_scRNA(
    arguments: dict, driver, model_provider: Optional[ModelProviderPort] = None
) -> dict:
    """Tier A/B hybrid: real scanpy Leiden clustering + Wilcoxon marker-gene
    identification run inside the sandbox; cell-type naming from those
    markers is a real BYOK LLM call made from THIS trusted process (never
    inside the sandbox) via `ModelClientFactory`."""
    validated = AnnotateCelltypeScrnaArgs(**(arguments or {}))
    sandbox_result = run_in_sandbox(
        driver, script_body=_SCRIPT_ANNOTATE_CELLTYPE_SCRNA, args=validated.model_dump()
    )
    clusters: Dict[str, Any] = sandbox_result.get("clusters", {})
    ontology_candidates: List[str] = sandbox_result.get("ontology_candidates") or []

    provider = model_provider if model_provider is not None else ModelClientFactory.get_client(validated.llm)

    annotations: Dict[str, Dict[str, Any]] = {}
    for cluster_id, info in clusters.items():
        lines = [
            f"Dataset context: {validated.data_info}.",
            f"Cluster {cluster_id} top marker genes: {', '.join(info.get('top_genes', []))}.",
            f"Cluster size: {info.get('n_cells', 0)} cells.",
        ]
        comp_context = _composition_context(validated.composition, cluster_id)
        if comp_context:
            lines.append(f"Reference-transferred composition for this cluster: {comp_context}.")
        if ontology_candidates:
            lines.append(
                "Prefer a name from this cell-ontology vocabulary when it fits: "
                + ", ".join(ontology_candidates)
            )
        raw = await provider.generate_response(
            prompt="\n".join(lines),
            system_instruction=_ANNOTATION_SYSTEM_INSTRUCTION,
            temperature=0.0,
        )
        parts = [p.strip() for p in raw.split(";", 2)]
        annotations[cluster_id] = {
            "cell_type": parts[0] if parts else raw.strip(),
            "confidence": parts[1] if len(parts) > 1 else "",
            "reason": parts[2] if len(parts) > 2 else "",
            "marker_genes": info.get("top_genes", []),
        }
    return {"cluster_annotations": annotations, "data_info": validated.data_info}


# ==========================================================================
# create_scvi_embeddings_scRNA (Tier A -- scvi-tools)
# ==========================================================================

class CreateScviEmbeddingsScrnaArgs(BaseModel):
    adata_filename: str
    batch_key: str
    label_key: str
    data_dir: str

    @model_validator(mode="after")
    def _check_adata_path(self) -> "CreateScviEmbeddingsScrnaArgs":
        _validate_relative_pair(self.data_dir, self.adata_filename)
        return self


_SCRIPT_CREATE_SCVI_EMBEDDINGS_SCRNA = """
import numpy as _np
import scanpy as _sc
import scvi as _scvi

_adata = _sc.read_h5ad(f"/workspace/{_args['data_dir']}/{_args['adata_filename']}")
_scvi.model.SCVI.setup_anndata(_adata, batch_key=_args['batch_key'])
_model = _scvi.model.SCVI(_adata, n_latent=10)
_model.train(max_epochs=20)
_scvi_latent = _model.get_latent_representation()

_lvae = _scvi.model.SCANVI.from_scvi_model(
    _model, adata=_adata, labels_key=_args['label_key'], unlabeled_category='Unknown'
)
_lvae.train(max_epochs=20)
_scanvi_latent = _lvae.get_latent_representation(_adata)


def _summary(_mat):
    return {
        "shape": list(_mat.shape),
        "mean_per_dim": [float(_v) for _v in _np.mean(_mat, axis=0)[:10]],
        "std_per_dim": [float(_v) for _v in _np.std(_mat, axis=0)[:10]],
        "preview": [[float(_v) for _v in _row] for _row in _mat[:5].tolist()],
    }


print(_json.dumps({
    "n_cells": int(_adata.n_obs),
    "scvi_latent": _summary(_scvi_latent),
    "scanvi_latent": _summary(_scanvi_latent),
}))
""".strip()


def create_scvi_embeddings_scRNA(arguments: dict, driver) -> dict:
    """Tier A: real scVI + scANVI training (`scvi-tools`) inside the sandbox.
    Returns latent-embedding summary statistics (shape, per-dimension
    mean/std, a small preview) rather than the full matrix or a saved
    `.h5ad` -- `/workspace` is read-only inside the jail, see module
    docstring."""
    validated = CreateScviEmbeddingsScrnaArgs(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_CREATE_SCVI_EMBEDDINGS_SCRNA, args=validated.model_dump()
    )


# ==========================================================================
# create_harmony_embeddings_scRNA (Tier A -- harmony-pytorch)
# ==========================================================================

class CreateHarmonyEmbeddingsScrnaArgs(BaseModel):
    adata_filename: str
    batch_key: str
    data_dir: str

    @model_validator(mode="after")
    def _check_adata_path(self) -> "CreateHarmonyEmbeddingsScrnaArgs":
        _validate_relative_pair(self.data_dir, self.adata_filename)
        return self


_SCRIPT_CREATE_HARMONY_EMBEDDINGS_SCRNA = """
import numpy as _np
import scanpy as _sc
from harmony import harmonize as _harmonize

_adata = _sc.read_h5ad(f"/workspace/{_args['data_dir']}/{_args['adata_filename']}")
if 'X_pca' not in _adata.obsm:
    _sc.pp.normalize_total(_adata, target_sum=1e4)
    _sc.pp.log1p(_adata)
    _sc.pp.highly_variable_genes(_adata, n_top_genes=min(2000, _adata.n_vars))
    _adata = _adata[:, _adata.var['highly_variable']].copy()
    _sc.pp.scale(_adata, max_value=10)
    _n_comps = max(1, min(50, _adata.n_obs - 1, _adata.n_vars - 1))
    _sc.tl.pca(_adata, n_comps=_n_comps)

_embedding = _harmonize(_adata.obsm['X_pca'], _adata.obs, batch_key=_args['batch_key'])

print(_json.dumps({
    "n_cells": int(_adata.n_obs),
    "shape": list(_embedding.shape),
    "mean_per_dim": [float(_v) for _v in _np.mean(_embedding, axis=0)[:10]],
    "std_per_dim": [float(_v) for _v in _np.std(_embedding, axis=0)[:10]],
    "preview": [[float(_v) for _v in _row] for _row in _embedding[:5].tolist()],
}))
""".strip()


def create_harmony_embeddings_scRNA(arguments: dict, driver) -> dict:
    """Tier A: real Harmony batch-integration (`harmony-pytorch`'s
    `harmonize`) inside the sandbox over a (computed-if-absent) PCA
    embedding. Returns summary statistics, see module docstring's note on
    `/workspace` being read-only."""
    validated = CreateHarmonyEmbeddingsScrnaArgs(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_CREATE_HARMONY_EMBEDDINGS_SCRNA, args=validated.model_dump()
    )


# ==========================================================================
# get_uce_embeddings_scRNA / map_to_ima_interpret_scRNA (Tier D)
# ==========================================================================

class GetUceEmbeddingsScrnaArgs(BaseModel):
    adata_filename: str
    data_dir: str
    DATA_ROOT: str = f"{DATA_LAKE_MOUNT}/singlecell/"
    custom_args: Optional[List[str]] = None


class MapToImaInterpretScrnaArgs(BaseModel):
    adata_filename: str
    data_dir: str
    custom_args: Optional[Dict[str, Any]] = None


def get_uce_embeddings_scRNA(arguments: dict, driver) -> dict:
    """Tier D -- see `backend/docs/tools/UNSUPPORTED.md`."""
    GetUceEmbeddingsScrnaArgs(**(arguments or {}))
    raise NotSupportedError(
        "get_uce_embeddings_scRNA requires the published Universal Cell Embeddings (UCE) "
        "pretrained checkpoint (multi-GB) plus a CUDA GPU host, neither of which is bundled "
        "or available in this single-local-server deployment; see "
        "backend/docs/tools/UNSUPPORTED.md."
    )


def map_to_ima_interpret_scRNA(arguments: dict, driver) -> dict:
    """Tier D -- see `backend/docs/tools/UNSUPPORTED.md`."""
    MapToImaInterpretScrnaArgs(**(arguments or {}))
    raise NotSupportedError(
        "map_to_ima_interpret_scRNA maps UCE embeddings onto the Integrated Megascale Atlas "
        "reference and is downstream of get_uce_embeddings_scRNA -- same missing UCE "
        "checkpoint + GPU dependency; see backend/docs/tools/UNSUPPORTED.md."
    )


# ==========================================================================
# get_rna_seq_archs4 (Tier A -- gget, needs network)
# ==========================================================================

class GetRnaSeqArchs4Args(BaseModel):
    gene_name: str
    K: int = Field(default=10, ge=1)


_SCRIPT_GET_RNA_SEQ_ARCHS4 = """
import gget as _gget

_df = _gget.archs4(_args['gene_name'], which='tissue')
_rows = _df.head(_args['K'])
_tissues = [{"tissue": str(_r['id']), "median_tpm": float(_r['median'])} for _, _r in _rows.iterrows()]

print(_json.dumps({"gene_name": _args['gene_name'], "tissues": _tissues}))
""".strip()


def get_rna_seq_archs4(arguments: dict, driver) -> dict:
    """Tier A: real ARCHS4 tissue-expression lookup via `gget.archs4`. NEEDS
    OUTBOUND NETWORK ACCESS (ARCHS4's own web API) -- requires a sandbox
    driver constructed with `allow_network=True`; with the default
    network-isolated driver this fails loud with a connection error rather
    than fabricating tissue TPM values."""
    validated = GetRnaSeqArchs4Args(**(arguments or {}))
    return run_in_sandbox(driver, script_body=_SCRIPT_GET_RNA_SEQ_ARCHS4, args=validated.model_dump())


# ==========================================================================
# get_gene_set_enrichment_analysis_supported_database_list (Tier A -- gseapy, needs network)
# ==========================================================================

class GetGeneSetEnrichmentAnalysisSupportedDatabaseListArgs(BaseModel):
    pass


_SCRIPT_GET_GSEA_SUPPORTED_DATABASES = """
import gseapy as _gseapy

_names = _gseapy.get_library_name()
print(_json.dumps({"databases": list(_names)}))
""".strip()


def get_gene_set_enrichment_analysis_supported_database_list(arguments: dict, driver) -> dict:
    """Tier A: real Enrichr library catalog via `gseapy.get_library_name()`.
    NEEDS OUTBOUND NETWORK ACCESS -- see `get_rna_seq_archs4`'s docstring."""
    GetGeneSetEnrichmentAnalysisSupportedDatabaseListArgs(**(arguments or {}))
    return run_in_sandbox(driver, script_body=_SCRIPT_GET_GSEA_SUPPORTED_DATABASES, args={})


# ==========================================================================
# gene_set_enrichment_analysis (Tier A -- gget, needs network)
# ==========================================================================

class GeneSetEnrichmentAnalysisArgs(BaseModel):
    genes: List[str] = Field(min_length=1)
    top_k: int = Field(default=10, ge=1)
    database: str = "ontology"
    background_list: Optional[List[str]] = None
    plot: bool = False


_SCRIPT_GENE_SET_ENRICHMENT_ANALYSIS = """
import gget as _gget

_df = _gget.enrichr(
    _args['genes'], database=_args['database'], background_list=_args['background_list'], plot=False
)
_df = _df.head(_args['top_k'])
_results = []
for _, _row in _df.iterrows():
    _results.append({
        "rank": int(_row['rank']),
        "path_name": str(_row['path_name']),
        "p_val": float(_row['p_val']),
        "z_score": float(_row['z_score']),
        "combined_score": float(_row['combined_score']),
        "overlapping_genes": list(_row['overlapping_genes']),
        "adj_p_val": float(_row['adj_p_val']),
        "database": str(_row['database']),
    })

print(_json.dumps({"results": _results}))
""".strip()


def gene_set_enrichment_analysis(arguments: dict, driver) -> dict:
    """Tier A: real Enrichr-backed gene-set enrichment via `gget.enrichr`.
    NEEDS OUTBOUND NETWORK ACCESS -- see `get_rna_seq_archs4`'s docstring.
    `plot` is accepted for catalog-signature compatibility but always runs
    with plotting disabled (the sandbox has no display); the result includes
    `plot_requested_but_unsupported` when the caller asked for `plot=True`."""
    validated = GeneSetEnrichmentAnalysisArgs(**(arguments or {}))
    result = run_in_sandbox(
        driver, script_body=_SCRIPT_GENE_SET_ENRICHMENT_ANALYSIS, args=validated.model_dump()
    )
    if validated.plot:
        result["plot_requested_but_unsupported"] = True
    return result


# ==========================================================================
# analyze_chromatin_interactions (Tier A -- cooler)
# ==========================================================================

class AnalyzeChromatinInteractionsArgs(BaseModel):
    hic_file_path: str
    regulatory_elements_bed: str
    output_dir: str = "./output"

    @field_validator("hic_file_path", "regulatory_elements_bed", "output_dir")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)


_SCRIPT_ANALYZE_CHROMATIN_INTERACTIONS = """
import cooler as _cooler
import numpy as _np
import pandas as _pd

_c = _cooler.Cooler(f"/workspace/{_args['hic_file_path']}")
_reg = _pd.read_csv(
    f"/workspace/{_args['regulatory_elements_bed']}", sep='\\t', header=None,
    names=['chrom', 'start', 'end', 'name', 'score', 'strand'],
)
_enhancers = _reg[_reg['name'].str.contains('enhancer', case=False, na=False)]
_promoters = _reg[_reg['name'].str.contains('promoter', case=False, na=False)]

_interactions = []
for _chrom in _c.chromnames:
    try:
        _mat = _c.matrix(balance=False).fetch(_chrom)
    except Exception:
        continue
    _chrom_enh = _enhancers[_enhancers['chrom'] == _chrom]
    _chrom_prom = _promoters[_promoters['chrom'] == _chrom]
    if _chrom_enh.empty or _chrom_prom.empty:
        continue
    for _, _enh in _chrom_enh.iterrows():
        _enh_bin = int(_enh['start'] // _c.binsize)
        if _enh_bin >= _mat.shape[0]:
            continue
        for _, _prom in _chrom_prom.iterrows():
            _prom_bin = int(_prom['start'] // _c.binsize)
            if _prom_bin >= _mat.shape[0]:
                continue
            _distance = abs(_enh_bin - _prom_bin)
            if _distance == 0:
                continue
            _strength = float(_mat[_enh_bin, _prom_bin])
            _diag = _np.diagonal(_mat, offset=_distance)
            _expected = float(_np.nanmean(_diag)) if _diag.size else 0.0
            _fold = _strength / _expected if _expected > 0 else 0.0
            if _fold > 2:
                _interactions.append({
                    "chrom": _chrom, "enhancer_name": str(_enh['name']),
                    "enhancer_start": int(_enh['start']), "promoter_name": str(_prom['name']),
                    "promoter_start": int(_prom['start']), "fold_enrichment": _fold,
                })

print(_json.dumps({
    "resolution_bp": int(_c.binsize) if _c.binsize else None,
    "chromosomes": list(_c.chromnames),
    "n_enhancers": int(len(_enhancers)),
    "n_promoters": int(len(_promoters)),
    "n_significant_interactions": len(_interactions),
    "significant_interactions": _interactions[:200],
}))
""".strip()


def analyze_chromatin_interactions(arguments: dict, driver) -> dict:
    """Tier A: real Hi-C enhancer-promoter interaction analysis via `cooler`.
    "Significant" = observed/expected (by genomic-distance diagonal) fold
    enrichment > 2, a documented heuristic threshold, not a fabricated
    p-value."""
    validated = AnalyzeChromatinInteractionsArgs(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_ANALYZE_CHROMATIN_INTERACTIONS, args=validated.model_dump()
    )


# ==========================================================================
# analyze_comparative_genomics_and_haplotypes (Tier A -- bwa+samtools+bcftools)
# ==========================================================================

class AnalyzeComparativeGenomicsAndHaplotypesArgs(BaseModel):
    sample_fasta_files: List[str] = Field(min_length=1)
    reference_genome_path: str
    output_dir: str = "./output"

    @field_validator("sample_fasta_files")
    @classmethod
    def _check_samples(cls, value: List[str]) -> List[str]:
        return _validate_paths(value)

    @field_validator("reference_genome_path", "output_dir")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)


_SCRIPT_ANALYZE_COMPARATIVE_GENOMICS_AND_HAPLOTYPES = """
import os as _os
import subprocess as _subprocess
import tempfile as _tempfile


def _run(_argv):
    _r = _subprocess.run(_argv, capture_output=True, text=True)
    if _r.returncode != 0:
        raise RuntimeError(f"{_argv[0]} failed (exit {_r.returncode}): {_r.stderr[-2000:]}")
    return _r.stdout


_work = _tempfile.mkdtemp(prefix='osw_compgen_')
_ref = f"/workspace/{_args['reference_genome_path']}"
_run(['bwa', 'index', _ref])
_run(['samtools', 'faidx', _ref])

_variant_counts = {}
_variant_sets = {}
for _sample_rel in _args['sample_fasta_files']:
    _sample_path = f"/workspace/{_sample_rel}"
    _name = _os.path.splitext(_os.path.basename(_sample_rel))[0]

    _sam_text = _run(['bwa', 'mem', _ref, _sample_path])
    _sam_path = _os.path.join(_work, f"{_name}.sam")
    with open(_sam_path, 'w') as _fh:
        _fh.write(_sam_text)

    _bam_path = _os.path.join(_work, f"{_name}.bam")
    _run(['samtools', 'sort', '-o', _bam_path, _sam_path])
    _run(['samtools', 'index', _bam_path])

    _mpileup_text = _run(['bcftools', 'mpileup', '-f', _ref, _bam_path])
    _mpileup_path = _os.path.join(_work, f"{_name}.mpileup.vcf")
    with open(_mpileup_path, 'w') as _fh:
        _fh.write(_mpileup_text)

    _vcf_path = _os.path.join(_work, f"{_name}.vcf")
    _run(['bcftools', 'call', '-mv', '-Ov', '-o', _vcf_path, _mpileup_path])

    _positions = set()
    with open(_vcf_path) as _fh:
        for _line in _fh:
            if _line.startswith('#'):
                continue
            _cols = _line.split('\\t')
            if len(_cols) >= 2:
                _positions.add((_cols[0], _cols[1]))
    _variant_counts[_name] = len(_positions)
    _variant_sets[_name] = _positions

_shared = set.intersection(*_variant_sets.values()) if _variant_sets else set()
_unique_counts = {_n: len(_s - _shared) for _n, _s in _variant_sets.items()}

print(_json.dumps({
    "samples": list(_variant_sets.keys()),
    "variant_counts_per_sample": _variant_counts,
    "shared_variant_count": len(_shared),
    "unique_variant_counts_per_sample": _unique_counts,
}))
""".strip()


def analyze_comparative_genomics_and_haplotypes(arguments: dict, driver) -> dict:
    """Tier A: real comparative-genomics pipeline -- `bwa mem` alignment of
    each sample against the reference, `samtools sort`/`index`, `bcftools
    mpileup`/`call` variant calling, then a real set-intersection over
    called-variant positions to report shared vs sample-unique variants.
    (This intentionally does NOT reproduce Biomni's own reference
    implementation of this tool, which falls back to `random.randint`-based
    fake haplotype groupings when BWA isn't available -- that would be a
    fabricated numeric result, which this project's tools never return.)"""
    validated = AnalyzeComparativeGenomicsAndHaplotypesArgs(**(arguments or {}))
    return run_in_sandbox(
        driver,
        script_body=_SCRIPT_ANALYZE_COMPARATIVE_GENOMICS_AND_HAPLOTYPES,
        args=validated.model_dump(),
    )


# ==========================================================================
# perform_chipseq_peak_calling_with_macs2 (Tier A -- MACS2)
# ==========================================================================

class PerformChipseqPeakCallingWithMacs2Args(BaseModel):
    chip_seq_file: str
    control_file: str
    output_name: str = "macs2_output"
    genome_size: str = "hs"
    q_value: float = Field(default=0.05, gt=0, lt=1)

    @field_validator("chip_seq_file", "control_file", "output_name")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)


_SCRIPT_PERFORM_CHIPSEQ_PEAK_CALLING_WITH_MACS2 = """
import os as _os
import subprocess as _subprocess
import tempfile as _tempfile

_outdir = _tempfile.mkdtemp(prefix='osw_macs2_')
_cmd = [
    'macs2', 'callpeak',
    '-t', f"/workspace/{_args['chip_seq_file']}",
    '-c', f"/workspace/{_args['control_file']}",
    '-n', _args['output_name'],
    '-g', _args['genome_size'],
    '-q', str(_args['q_value']),
    '--outdir', _outdir,
]
_r = _subprocess.run(_cmd, capture_output=True, text=True)
if _r.returncode != 0:
    raise RuntimeError(f"macs2 callpeak failed: {_r.stderr[-2000:]}")

_narrowpeak = _os.path.join(_outdir, f"{_args['output_name']}_peaks.narrowPeak")
_n_peaks = 0
_preview = []
if _os.path.exists(_narrowpeak):
    with open(_narrowpeak) as _fh:
        for _line in _fh:
            _n_peaks += 1
            if len(_preview) < 50:
                _cols = _line.rstrip('\\n').split('\\t')
                if len(_cols) >= 7:
                    _preview.append({
                        "chrom": _cols[0], "start": int(_cols[1]), "end": int(_cols[2]),
                        "name": _cols[3],
                        "score": float(_cols[4]) if _cols[4] else None,
                        "fold_enrichment": float(_cols[6]) if _cols[6] else None,
                    })

print(_json.dumps({
    "n_peaks": _n_peaks, "peaks_preview": _preview,
    "genome_size": _args['genome_size'], "q_value": _args['q_value'],
}))
""".strip()


def perform_chipseq_peak_calling_with_macs2(arguments: dict, driver) -> dict:
    """Tier A: real ChIP-seq peak calling via `macs2 callpeak`."""
    validated = PerformChipseqPeakCallingWithMacs2Args(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_PERFORM_CHIPSEQ_PEAK_CALLING_WITH_MACS2, args=validated.model_dump()
    )


# ==========================================================================
# find_enriched_motifs_with_homer (Tier A -- HOMER)
# ==========================================================================

class FindEnrichedMotifsWithHomerArgs(BaseModel):
    peak_file: str
    genome: str = "hg38"
    background_file: Optional[str] = None
    motif_length: str = "8,10,12"
    output_dir: str = "./homer_motifs"
    num_motifs: int = Field(default=10, ge=1)
    threads: int = Field(default=4, ge=1)

    @field_validator("peak_file", "output_dir")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)

    @field_validator("background_file")
    @classmethod
    def _check_optional_path(cls, value: Optional[str]) -> Optional[str]:
        return _validate_optional_path(value)


_SCRIPT_FIND_ENRICHED_MOTIFS_WITH_HOMER = """
import glob as _glob
import os as _os
import subprocess as _subprocess
import tempfile as _tempfile

_outdir = _tempfile.mkdtemp(prefix='osw_homer_')
_cmd = [
    'findMotifsGenome.pl', f"/workspace/{_args['peak_file']}", _args['genome'], _outdir,
    '-size', '200', '-len', _args['motif_length'],
    '-S', str(_args['num_motifs']), '-p', str(_args['threads']),
]
if _args.get('background_file'):
    _cmd += ['-bg', f"/workspace/{_args['background_file']}"]

_r = _subprocess.run(_cmd, capture_output=True, text=True)
if _r.returncode != 0:
    raise RuntimeError(f"HOMER findMotifsGenome.pl failed: {_r.stderr[-2000:]}")

_motif_files = sorted(_glob.glob(_os.path.join(_outdir, 'homerResults', 'motif*.motif')))
_de_novo = []
for _mf in _motif_files[:20]:
    with open(_mf) as _fh:
        _header = _fh.readline().strip()
    _parts = _header.split('\\t')
    _de_novo.append({
        "consensus": _parts[0].lstrip('>') if _parts else None,
        "match": _parts[1] if len(_parts) > 1 else None,
        "p_value": _parts[2] if len(_parts) > 2 else None,
    })

_known_path = _os.path.join(_outdir, 'knownResults.txt')
_known = []
if _os.path.exists(_known_path):
    with open(_known_path) as _fh:
        _lines = _fh.readlines()
    for _line in _lines[1:11]:
        _cols = _line.rstrip('\\n').split('\\t')
        if len(_cols) >= 4:
            _known.append({"name": _cols[0], "p_value": _cols[2]})

print(_json.dumps({
    "n_de_novo_motifs": len(_motif_files), "de_novo_motifs": _de_novo, "known_motifs": _known,
}))
""".strip()


def find_enriched_motifs_with_homer(arguments: dict, driver) -> dict:
    """Tier A: real motif discovery via HOMER's `findMotifsGenome.pl`."""
    validated = FindEnrichedMotifsWithHomerArgs(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_FIND_ENRICHED_MOTIFS_WITH_HOMER, args=validated.model_dump()
    )


# ==========================================================================
# analyze_genomic_region_overlap (Tier A -- pybedtools)
# ==========================================================================

class AnalyzeGenomicRegionOverlapArgs(BaseModel):
    region_sets: List[str] = Field(min_length=1)
    output_prefix: str = "overlap_analysis"

    @field_validator("region_sets")
    @classmethod
    def _check_region_sets(cls, value: List[str]) -> List[str]:
        return _validate_paths(value)

    @field_validator("output_prefix")
    @classmethod
    def _check_prefix(cls, value: str) -> str:
        return _validate_path(value)


_SCRIPT_ANALYZE_GENOMIC_REGION_OVERLAP = """
import pybedtools as _pybedtools

_bts = [_pybedtools.BedTool(f"/workspace/{_p}") for _p in _args['region_sets']]
_names = [f"Region_Set_{_i + 1}" for _i in range(len(_bts))]

_set_stats = []
for _name, _bt in zip(_names, _bts):
    _bp = sum(int(_f.end) - int(_f.start) for _f in _bt)
    _set_stats.append({"name": _name, "n_regions": len(_bt), "total_bp": _bp})

_pairs = []
for _i in range(len(_bts)):
    for _j in range(_i + 1, len(_bts)):
        _overlap = _bts[_i].intersect(_bts[_j], u=True)
        _overlap_wo = _bts[_i].intersect(_bts[_j], wo=True)
        _overlap_bp = 0
        for _line in _overlap_wo:
            _fields = [str(_f) for _f in _line]
            try:
                _overlap_bp += int(_fields[-1])
            except (ValueError, IndexError):
                pass
        _bp_i = _set_stats[_i]['total_bp']
        _bp_j = _set_stats[_j]['total_bp']
        _pairs.append({
            "set1": _names[_i], "set2": _names[_j],
            "overlap_regions": len(_overlap), "overlap_bp": _overlap_bp,
            "pct_of_set1": (_overlap_bp / _bp_i * 100) if _bp_i else 0.0,
            "pct_of_set2": (_overlap_bp / _bp_j * 100) if _bp_j else 0.0,
        })

print(_json.dumps({"sets": _set_stats, "pairwise_overlaps": _pairs}))
""".strip()


def analyze_genomic_region_overlap(arguments: dict, driver) -> dict:
    """Tier A: real pairwise BED-region overlap analysis via `pybedtools`
    (`bedtools` under the hood)."""
    validated = AnalyzeGenomicRegionOverlapArgs(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_ANALYZE_GENOMIC_REGION_OVERLAP, args=validated.model_dump()
    )


# ==========================================================================
# analyze_atac_seq_differential_accessibility (Tier A -- MACS2)
# ==========================================================================

class AnalyzeAtacSeqDifferentialAccessibilityArgs(BaseModel):
    treatment_bam: str
    control_bam: str
    output_dir: str = "./atac_results"
    genome_size: str = "hs"
    q_value: float = Field(default=0.05, gt=0, lt=1)
    name_prefix: str = "atac"

    @field_validator("treatment_bam", "control_bam", "output_dir", "name_prefix")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)


_SCRIPT_ANALYZE_ATAC_SEQ_DIFFERENTIAL_ACCESSIBILITY = """
import os as _os
import subprocess as _subprocess
import tempfile as _tempfile

_outdir = _tempfile.mkdtemp(prefix='osw_atac_')


def _macs2_call(_bam_path, _name):
    _cmd = [
        'macs2', 'callpeak', '-t', _bam_path, '-f', 'BAM', '-g', _args['genome_size'],
        '-n', _name, '--outdir', _outdir, '--nomodel', '--shift', '-100', '--extsize', '200',
        '-q', str(_args['q_value']),
    ]
    _r = _subprocess.run(_cmd, capture_output=True, text=True)
    if _r.returncode != 0:
        raise RuntimeError(f"macs2 callpeak failed for {_name}: {_r.stderr[-2000:]}")
    _peaks_file = _os.path.join(_outdir, f"{_name}_peaks.narrowPeak")
    _count = 0
    if _os.path.exists(_peaks_file):
        with open(_peaks_file) as _fh:
            _count = sum(1 for _ in _fh)
    return _count


_treat_name = f"{_args['name_prefix']}_treatment"
_ctrl_name = f"{_args['name_prefix']}_control"
_treat_peaks = _macs2_call(f"/workspace/{_args['treatment_bam']}", _treat_name)
_ctrl_peaks = _macs2_call(f"/workspace/{_args['control_bam']}", _ctrl_name)

_diff_prefix = _os.path.join(_outdir, f"{_args['name_prefix']}_differential")
_diff_cmd = [
    'macs2', 'bdgdiff',
    '--t1', _os.path.join(_outdir, f"{_treat_name}_treat_pileup.bdg"),
    '--c1', _os.path.join(_outdir, f"{_treat_name}_control_lambda.bdg"),
    '--t2', _os.path.join(_outdir, f"{_ctrl_name}_treat_pileup.bdg"),
    '--c2', _os.path.join(_outdir, f"{_ctrl_name}_control_lambda.bdg"),
    '--d1', '1', '--d2', '1', '--o-prefix', _diff_prefix,
]
_r = _subprocess.run(_diff_cmd, capture_output=True, text=True)
if _r.returncode != 0:
    raise RuntimeError(f"macs2 bdgdiff failed: {_r.stderr[-2000:]}")

_treat_enriched = 0
_ctrl_enriched = 0
_cond1 = f"{_diff_prefix}_c3.0_cond1.bed"
_cond2 = f"{_diff_prefix}_c3.0_cond2.bed"
if _os.path.exists(_cond1):
    with open(_cond1) as _fh:
        _treat_enriched = sum(1 for _ in _fh)
if _os.path.exists(_cond2):
    with open(_cond2) as _fh:
        _ctrl_enriched = sum(1 for _ in _fh)

print(_json.dumps({
    "treatment_peaks": _treat_peaks, "control_peaks": _ctrl_peaks,
    "differential_treatment_enriched": _treat_enriched,
    "differential_control_enriched": _ctrl_enriched,
    "bdgdiff_exit_code": _r.returncode,
}))
""".strip()


def analyze_atac_seq_differential_accessibility(arguments: dict, driver) -> dict:
    """Tier A: real ATAC-seq peak calling (`macs2 callpeak --nomodel --shift
    -100 --extsize 200`, the standard ATAC-seq shift/extsize convention) on
    treatment and control, then real differential-accessibility calling via
    `macs2 bdgdiff`."""
    validated = AnalyzeAtacSeqDifferentialAccessibilityArgs(**(arguments or {}))
    return run_in_sandbox(
        driver,
        script_body=_SCRIPT_ANALYZE_ATAC_SEQ_DIFFERENTIAL_ACCESSIBILITY,
        args=validated.model_dump(),
    )


# ==========================================================================
# analyze_ddr_network_in_cancer (Tier B -- networkx + scipy correlation)
# ==========================================================================

class AnalyzeDdrNetworkInCancerArgs(BaseModel):
    expression_data_path: str
    mutation_data_path: str
    output_dir: str = "./results"

    @field_validator("expression_data_path", "mutation_data_path", "output_dir")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)


_SCRIPT_ANALYZE_DDR_NETWORK_IN_CANCER = """
import networkx as _nx
import pandas as _pd
from scipy.stats import pearsonr as _pearsonr

_expr = _pd.read_csv(f"/workspace/{_args['expression_data_path']}", index_col=0)
_mut = _pd.read_csv(f"/workspace/{_args['mutation_data_path']}", index_col=0)

_DDR_GENES = [
    "ATM", "ATR", "PRKDC", "RAD50", "MRE11", "NBN", "CHEK1", "CHEK2", "TP53", "BRCA1",
    "BRCA2", "MDC1", "RAD51", "RAD52", "PALB2", "RAD54L", "XRCC4", "LIG4", "XRCC5", "XRCC6",
    "PARP1", "APEX1", "OGG1", "XRCC1", "XPA", "XPC", "ERCC1", "ERCC2", "ERCC3", "ERCC4",
    "ERCC5", "MLH1", "MSH2", "MSH6", "PMS2",
]
_ddr_expr = _expr.loc[_expr.index.isin(_DDR_GENES)]
_ddr_mut = _mut.loc[_mut.index.isin(_DDR_GENES)]

_g = _nx.Graph()
for _gene in _ddr_expr.index:
    _freq = float(_ddr_mut.loc[_gene].mean()) if _gene in _ddr_mut.index else 0.0
    _g.add_node(_gene, mutation_freq=_freq)

_genes_list = list(_ddr_expr.index)
for _i, _g1 in enumerate(_genes_list):
    for _g2 in _genes_list[_i + 1:]:
        _corr, _p = _pearsonr(_ddr_expr.loc[_g1], _ddr_expr.loc[_g2])
        if abs(_corr) > 0.4 and _p < 0.05:
            _g.add_edge(_g1, _g2, weight=abs(_corr), correlation=float(_corr))

_degree = _nx.degree_centrality(_g)
_between = _nx.betweenness_centrality(_g)
_hub = sorted(_degree.items(), key=lambda _x: _x[1], reverse=True)[:5]
_bottleneck = sorted(_between.items(), key=lambda _x: _x[1], reverse=True)[:5]
_mut_freq = {_n: _g.nodes[_n]['mutation_freq'] for _n in _g.nodes()}
_top_mutated = sorted(_mut_freq.items(), key=lambda _x: _x[1], reverse=True)[:5]

try:
    _avg_clustering = _nx.average_clustering(_g)
except Exception:
    _avg_clustering = None

print(_json.dumps({
    "n_ddr_genes_found": len(_ddr_expr),
    "n_network_edges": _g.number_of_edges(),
    "hub_genes": [{"gene": _gname, "degree_centrality": _v} for _gname, _v in _hub],
    "bottleneck_genes": [{"gene": _gname, "betweenness_centrality": _v} for _gname, _v in _bottleneck],
    "frequently_mutated_genes": [{"gene": _gname, "mutation_frequency": _v} for _gname, _v in _top_mutated],
    "network_density": _nx.density(_g) if _g.number_of_nodes() > 1 else 0.0,
    "average_clustering_coefficient": _avg_clustering,
}))
""".strip()


def analyze_ddr_network_in_cancer(arguments: dict, driver) -> dict:
    """Tier B: real DNA-Damage-Response gene-gene correlation network
    (Pearson correlation over expression, |r|>0.4 and p<0.05 as edges) +
    real `networkx` degree/betweenness centrality and clustering stats.
    Does not include an Enrichr GSEA cross-check (would need outbound
    network access) -- structural/centrality stats only."""
    validated = AnalyzeDdrNetworkInCancerArgs(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_ANALYZE_DDR_NETWORK_IN_CANCER, args=validated.model_dump()
    )


# ==========================================================================
# detect_and_annotate_somatic_mutations (Tier A -- GATK Mutect2 + SnpEff)
# ==========================================================================

class DetectAndAnnotateSomaticMutationsArgs(BaseModel):
    tumor_bam: str
    normal_bam: str
    reference_genome: str
    output_prefix: str
    snpeff_database: str = "GRCh38.105"

    @field_validator("tumor_bam", "normal_bam", "reference_genome", "output_prefix")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)


_SCRIPT_DETECT_AND_ANNOTATE_SOMATIC_MUTATIONS = """
import os as _os
import subprocess as _subprocess
import tempfile as _tempfile


def _run(_argv):
    _r = _subprocess.run(_argv, capture_output=True, text=True)
    if _r.returncode != 0:
        raise RuntimeError(f"{_argv[0]} failed (exit {_r.returncode}): {_r.stderr[-2000:]}")
    return _r.stdout


_work = _tempfile.mkdtemp(prefix='osw_somatic_')
_ref = f"/workspace/{_args['reference_genome']}"
_tumor = f"/workspace/{_args['tumor_bam']}"
_normal = f"/workspace/{_args['normal_bam']}"
# NOTE: the matched-normal sample name is derived from the BAM's filename
# (the same simplification the upstream Biomni reference tool uses) rather
# than read out of the BAM's own @RG SM tag -- correct when the file is
# named after its sample, a documented limitation otherwise.
_normal_sample = _os.path.splitext(_os.path.basename(_args['normal_bam']))[0]

_raw_vcf = _os.path.join(_work, 'unfiltered.vcf')
_run(['gatk', 'Mutect2', '-R', _ref, '-I', _tumor, '-I', _normal, '-normal', _normal_sample, '-O', _raw_vcf])

_filtered_vcf = _os.path.join(_work, 'filtered.vcf')
_run(['gatk', 'FilterMutectCalls', '-R', _ref, '-V', _raw_vcf, '-O', _filtered_vcf])

_annotated_text = _run(['snpEff', '-noStats', _args['snpeff_database'], _filtered_vcf])
_annotated_vcf = _os.path.join(_work, 'annotated.vcf')
with open(_annotated_vcf, 'w') as _fh:
    _fh.write(_annotated_text)

_total = 0
_by_type = {"SNP": 0, "INS": 0, "DEL": 0}
_high_impact = 0
with open(_annotated_vcf) as _fh:
    for _line in _fh:
        if _line.startswith('#'):
            continue
        _total += 1
        for _t in _by_type:
            if _t in _line:
                _by_type[_t] += 1
        if 'HIGH' in _line:
            _high_impact += 1

print(_json.dumps({
    "output_prefix": _args['output_prefix'],
    "total_somatic_variants": _total,
    "variant_types": _by_type,
    "high_impact_variants": _high_impact,
}))
""".strip()


def detect_and_annotate_somatic_mutations(arguments: dict, driver) -> dict:
    """Tier A: real somatic variant calling -- `gatk Mutect2` (tumor vs
    matched normal) + `gatk FilterMutectCalls` + `snpEff` functional
    annotation. `snpEff`'s output is captured via `subprocess.run`'s
    `capture_output` and written to a file directly -- never via a shell
    redirect string (unlike Biomni's own reference implementation, which
    uses `shell=True` with string-joined argv, a command-injection
    footgun this project's tools never use)."""
    validated = DetectAndAnnotateSomaticMutationsArgs(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_DETECT_AND_ANNOTATE_SOMATIC_MUTATIONS, args=validated.model_dump()
    )


# ==========================================================================
# detect_and_characterize_structural_variations (Tier A -- LUMPY)
# ==========================================================================

class DetectAndCharacterizeStructuralVariationsArgs(BaseModel):
    bam_file_path: str
    reference_genome_path: str
    output_dir: str
    cosmic_db_path: Optional[str] = None
    clinvar_db_path: Optional[str] = None

    @field_validator("bam_file_path", "reference_genome_path", "output_dir")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)

    @field_validator("cosmic_db_path", "clinvar_db_path")
    @classmethod
    def _check_optional_paths(cls, value: Optional[str]) -> Optional[str]:
        return _validate_optional_path(value)


_SCRIPT_DETECT_AND_CHARACTERIZE_STRUCTURAL_VARIATIONS = """
import os as _os
import subprocess as _subprocess
import tempfile as _tempfile


def _run(_argv, _input_bytes=None):
    # NB: `input=` passes bytes as DATA to the child process's stdin -- this
    # is how a Unix pipe (`a | b`) is done safely with argv lists, never by
    # building a shell string.
    _r = _subprocess.run(_argv, capture_output=True, input=_input_bytes)
    if _r.returncode != 0:
        _stderr = (_r.stderr or b'')[-2000:]
        raise RuntimeError(f"{_argv[0]} failed (exit {_r.returncode}): {_stderr!r}")
    return _r.stdout


_work = _tempfile.mkdtemp(prefix='osw_sv_')
_bam = f"/workspace/{_args['bam_file_path']}"

_discordant_bam = _os.path.join(_work, 'discordant.bam')
_run(['samtools', 'view', '-b', '-F', '1294', '-o', _discordant_bam, _bam])

_sam_header_bytes = _run(['samtools', 'view', '-h', _bam])
_split_sam_bytes = _run(['extractSplitReads_BwaMem', '-i', 'stdin'], _input_bytes=_sam_header_bytes)
_split_bam_bytes = _run(['samtools', 'view', '-Sb', '-'], _input_bytes=_split_sam_bytes)
_split_bam = _os.path.join(_work, 'split.bam')
with open(_split_bam, 'wb') as _fh:
    _fh.write(_split_bam_bytes)

_vcf_out = _os.path.join(_work, 'structural_variants.vcf')
_run(['lumpyexpress', '-B', _bam, '-S', _split_bam, '-D', _discordant_bam, '-o', _vcf_out])

_filtered_vcf = _os.path.join(_work, 'filtered_sv.vcf')
_run(['bcftools', 'filter', '-i', 'QUAL>=100 && SVLEN>=100', '-o', _filtered_vcf, _vcf_out])

_sv_counts = {"DEL": 0, "DUP": 0, "INV": 0, "BND": 0, "INS": 0}
_records = []
with open(_filtered_vcf) as _fh:
    for _line in _fh:
        if _line.startswith('#'):
            continue
        for _t in _sv_counts:
            if f"SVTYPE={_t}" in _line:
                _sv_counts[_t] += 1
        _cols = _line.split('\\t')
        if len(_records) < 100 and len(_cols) >= 5:
            _records.append({"chrom": _cols[0], "pos": _cols[1]})


def _load_positions(_rel_path):
    _positions = set()
    if not _rel_path:
        return _positions
    _full = f"/workspace/{_rel_path}"
    if not _os.path.exists(_full):
        return _positions
    with open(_full) as _fh:
        for _line in _fh:
            if _line.startswith('#') or not _line.strip():
                continue
            _cols = _line.split('\\t')
            if len(_cols) >= 2:
                _positions.add((_cols[0], _cols[1]))
    return _positions


# Real (if simple) chrom+pos overlap lookup against whatever COSMIC/ClinVar
# TSV/VCF-like file was supplied -- NOT a placeholder that pretends to
# annotate by copying the input unchanged.
_cosmic_positions = _load_positions(_args.get('cosmic_db_path'))
_clinvar_positions = _load_positions(_args.get('clinvar_db_path'))
_cosmic_hits = sum(1 for _r in _records if (_r['chrom'], _r['pos']) in _cosmic_positions)
_clinvar_hits = sum(1 for _r in _records if (_r['chrom'], _r['pos']) in _clinvar_positions)

print(_json.dumps({
    "total_svs": sum(_sv_counts.values()),
    "sv_counts_by_type": _sv_counts,
    "records_preview": _records[:20],
    "cosmic_position_matches": _cosmic_hits,
    "clinvar_position_matches": _clinvar_hits,
}))
""".strip()


def detect_and_characterize_structural_variations(arguments: dict, driver) -> dict:
    """Tier A: real structural-variant detection -- `samtools` discordant +
    split-read extraction (piped via `subprocess`'s `input=` bytes, never a
    shell string), `lumpyexpress` SV calling, `bcftools filter` quality/size
    filtering, then a real chrom+pos overlap lookup against optional
    COSMIC/ClinVar database files (assumed tab-separated with CHROM in
    column 0 and POS in column 1, e.g. VCF/BED-like)."""
    validated = DetectAndCharacterizeStructuralVariationsArgs(**(arguments or {}))
    return run_in_sandbox(
        driver,
        script_body=_SCRIPT_DETECT_AND_CHARACTERIZE_STRUCTURAL_VARIATIONS,
        args=validated.model_dump(),
    )


# ==========================================================================
# perform_gene_expression_nmf_analysis (Tier B -- sklearn NMF)
# ==========================================================================

class PerformGeneExpressionNmfAnalysisArgs(BaseModel):
    expression_data_path: str
    n_components: int = Field(default=10, ge=1)
    normalize: bool = True
    output_dir: str = "nmf_results"
    random_state: int = 42

    @field_validator("expression_data_path", "output_dir")
    @classmethod
    def _check_paths(cls, value: str) -> str:
        return _validate_path(value)


_SCRIPT_PERFORM_GENE_EXPRESSION_NMF_ANALYSIS = """
import numpy as _np
import pandas as _pd
from sklearn.decomposition import NMF as _NMF

_path = f"/workspace/{_args['expression_data_path']}"
_sep = '\\t' if _path.endswith(('.tsv', '.txt')) else ','
_expr = _pd.read_csv(_path, sep=_sep, index_col=0)
_genes = _expr.index.tolist()
_samples = _expr.columns.tolist()
_x = _expr.values.astype(float)
if (_x < 0).any():
    _x = _np.abs(_x)
if _args['normalize']:
    _col_sums = _x.sum(axis=0, keepdims=True)
    _col_sums[_col_sums == 0] = 1.0
    _x = _x / _col_sums * 1000.0

_n_components = max(1, min(_args['n_components'], min(_x.shape)))
_model = _NMF(n_components=_n_components, init='random', random_state=_args['random_state'], max_iter=1000)
_w = _model.fit_transform(_x)
_h = _model.components_

_top_genes = {}
for _i in range(_n_components):
    _order = _np.argsort(_w[:, _i])[::-1][:20]
    _top_genes[f"Metagene_{_i + 1}"] = [_genes[_idx] for _idx in _order]

print(_json.dumps({
    "n_genes": len(_genes), "n_samples": len(_samples), "n_components": _n_components,
    "reconstruction_error": float(_model.reconstruction_err_),
    "n_iterations": int(_model.n_iter_),
    "top_genes_per_metagene": _top_genes,
    "sample_weights_preview": {
        f"Metagene_{_i + 1}": [float(_v) for _v in _h[_i][:10]] for _i in range(_n_components)
    },
}))
""".strip()


def perform_gene_expression_nmf_analysis(arguments: dict, driver) -> dict:
    """Tier B: real Non-negative Matrix Factorization over gene-expression
    data via `sklearn.decomposition.NMF` -- extracts metagenes (top genes
    per component) and sample weights for tumor-subtype-style analyses."""
    validated = PerformGeneExpressionNmfAnalysisArgs(**(arguments or {}))
    return run_in_sandbox(
        driver, script_body=_SCRIPT_PERFORM_GENE_EXPRESSION_NMF_ANALYSIS, args=validated.model_dump()
    )


# ==========================================================================
# Registration
# ==========================================================================

def _bind(handler, driver):
    """Wraps a `(arguments, driver) -> dict|coroutine` handler into the
    single-argument `(arguments) -> ...` shape `MCPServerRegistry` calls
    (see `server_registry.py::route`, which awaits the result when it's a
    coroutine -- so this works unchanged for both sync and `async def`
    handlers such as `annotate_celltype_scRNA`)."""

    def _call(arguments: dict):
        return handler(arguments, driver)

    return _call


def register_single_cell_omics_tools(registry, driver) -> List[str]:
    """Registers every single-cell/omics/regulatory-genomics action tool
    (Tier A/B AND Tier D -- Tier D tools are still registered, they just
    always fail loud via `NotSupportedError` when called, per
    `backend/docs/tools/UNSUPPORTED.md`'s own rules) into `registry`, bound
    to the given sandbox `driver`. Returns the registered tool names."""
    handlers = {
        "annotate_celltype_scRNA": annotate_celltype_scRNA,
        "create_scvi_embeddings_scRNA": create_scvi_embeddings_scRNA,
        "create_harmony_embeddings_scRNA": create_harmony_embeddings_scRNA,
        "get_uce_embeddings_scRNA": get_uce_embeddings_scRNA,
        "map_to_ima_interpret_scRNA": map_to_ima_interpret_scRNA,
        "get_rna_seq_archs4": get_rna_seq_archs4,
        "get_gene_set_enrichment_analysis_supported_database_list": (
            get_gene_set_enrichment_analysis_supported_database_list
        ),
        "gene_set_enrichment_analysis": gene_set_enrichment_analysis,
        "analyze_chromatin_interactions": analyze_chromatin_interactions,
        "analyze_comparative_genomics_and_haplotypes": analyze_comparative_genomics_and_haplotypes,
        "perform_chipseq_peak_calling_with_macs2": perform_chipseq_peak_calling_with_macs2,
        "find_enriched_motifs_with_homer": find_enriched_motifs_with_homer,
        "analyze_genomic_region_overlap": analyze_genomic_region_overlap,
        "analyze_atac_seq_differential_accessibility": analyze_atac_seq_differential_accessibility,
        "analyze_ddr_network_in_cancer": analyze_ddr_network_in_cancer,
        "detect_and_annotate_somatic_mutations": detect_and_annotate_somatic_mutations,
        "detect_and_characterize_structural_variations": detect_and_characterize_structural_variations,
        "perform_gene_expression_nmf_analysis": perform_gene_expression_nmf_analysis,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, _bind(handler, driver))
    return list(handlers.keys())
