"""Unit tests for `infrastructure/tools/single_cell_omics.py` (Fase 5).

Per `_sandbox_tool_base.py`'s "TESTING REALITY" docstring: `script_body`
strings import packages (scanpy/scvi-tools/cooler/gseapy/...) that only exist
in the sandbox toolkit's own conda env, never in this repo's pytest venv.
These tests therefore verify the WIRING and VALIDATION layer only -- via
`FakeSandboxDriver` -- not live scientific correctness.
"""
import pytest
from pydantic import ValidationError

from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.tools import single_cell_omics as tools
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver, NotSupportedError


class FakeModelProvider:
    """Test double for `ModelProviderPort` -- records prompts, returns a
    canned `generate_response` string (never touches the network)."""

    def __init__(self, response: str = "T cell; 0.9; matches CD3E/CD3D markers"):
        self.response = response
        self.calls = []

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        self.calls.append((prompt, system_instruction, temperature))
        return self.response

    def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0):
        raise NotImplementedError("unused by these tests")


# ---------------------------------------------------------------------------
# annotate_celltype_scRNA (Tier A/B hybrid: sandbox clustering + LLM call)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_annotate_celltype_scrna_round_trips_args_and_annotates_clusters():
    driver = FakeSandboxDriver()
    driver.stdout = (
        '{"clusters": {"0": {"top_genes": ["CD3E", "CD3D"], "n_cells": 120}}, '
        '"ontology_candidates": ["T cell", "B cell"]}'
    )
    fake_llm = FakeModelProvider()

    result = await tools.annotate_celltype_scRNA(
        {
            "adata_filename": "sample.h5ad",
            "data_dir": "data",
            "data_info": "homo sapiens, PBMC",
        },
        driver,
        model_provider=fake_llm,
    )

    assert driver.last_args() == {
        "adata_filename": "sample.h5ad",
        "data_dir": "data",
        "data_info": "homo sapiens, PBMC",
        "cluster": "leiden",
        "llm": "anthropic",
        "composition": None,
        "DATA_LAKE": "/datalake",
    }
    assert result["cluster_annotations"]["0"]["cell_type"] == "T cell"
    assert result["cluster_annotations"]["0"]["marker_genes"] == ["CD3E", "CD3D"]
    assert len(fake_llm.calls) == 1
    assert "CD3E" in fake_llm.calls[0][0]


@pytest.mark.asyncio
async def test_annotate_celltype_scrna_rejects_missing_required_field_before_sandbox_call():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        await tools.annotate_celltype_scRNA({"adata_filename": "sample.h5ad"}, driver)
    assert driver.calls == []


@pytest.mark.asyncio
async def test_annotate_celltype_scrna_rejects_path_traversal():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        await tools.annotate_celltype_scRNA(
            {
                "adata_filename": "../../etc/passwd",
                "data_dir": "data",
                "data_info": "homo sapiens",
            },
            driver,
        )
    assert driver.calls == []


@pytest.mark.asyncio
async def test_annotate_celltype_scrna_rejects_unsupported_llm_provider():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        await tools.annotate_celltype_scRNA(
            {
                "adata_filename": "sample.h5ad",
                "data_dir": "data",
                "data_info": "homo sapiens",
                "llm": "not-a-real-provider",
            },
            driver,
        )
    assert driver.calls == []


@pytest.mark.asyncio
async def test_annotate_celltype_scrna_rejects_data_lake_outside_mount():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        await tools.annotate_celltype_scRNA(
            {
                "adata_filename": "sample.h5ad",
                "data_dir": "data",
                "data_info": "homo sapiens",
                "DATA_LAKE": "/etc",
            },
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# create_scvi_embeddings_scRNA
# ---------------------------------------------------------------------------

def test_create_scvi_embeddings_scrna_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"n_cells": 500, "scvi_latent": {"shape": [500, 10]}, "scanvi_latent": {"shape": [500, 10]}}'

    result = tools.create_scvi_embeddings_scRNA(
        {
            "adata_filename": "sample.h5ad",
            "batch_key": "batch",
            "label_key": "cell_type",
            "data_dir": "data",
        },
        driver,
    )

    assert driver.last_args()["batch_key"] == "batch"
    assert result["n_cells"] == 500
    assert "scvi" in driver.calls[-1][0]


def test_create_scvi_embeddings_scrna_missing_required_field_raises_before_sandbox_call():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.create_scvi_embeddings_scRNA({"adata_filename": "sample.h5ad"}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# create_harmony_embeddings_scRNA
# ---------------------------------------------------------------------------

def test_create_harmony_embeddings_scrna_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"n_cells": 300, "shape": [300, 50]}'

    result = tools.create_harmony_embeddings_scRNA(
        {"adata_filename": "sample.h5ad", "batch_key": "batch", "data_dir": "data"}, driver
    )

    assert driver.last_args() == {
        "adata_filename": "sample.h5ad", "batch_key": "batch", "data_dir": "data",
    }
    assert result["n_cells"] == 300
    assert "harmonize" in driver.calls[-1][0]


def test_create_harmony_embeddings_scrna_rejects_traversal_in_data_dir():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.create_harmony_embeddings_scRNA(
            {"adata_filename": "sample.h5ad", "batch_key": "batch", "data_dir": "../../secrets"}, driver
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# get_uce_embeddings_scRNA / map_to_ima_interpret_scRNA (Tier D)
# ---------------------------------------------------------------------------

def test_get_uce_embeddings_scrna_is_not_supported():
    driver = FakeSandboxDriver()
    with pytest.raises(NotSupportedError, match="UNSUPPORTED.md"):
        tools.get_uce_embeddings_scRNA({"adata_filename": "s.h5ad", "data_dir": "data"}, driver)
    assert driver.calls == []


def test_map_to_ima_interpret_scrna_is_not_supported():
    driver = FakeSandboxDriver()
    with pytest.raises(NotSupportedError, match="UNSUPPORTED.md"):
        tools.map_to_ima_interpret_scRNA({"adata_filename": "s.h5ad", "data_dir": "data"}, driver)
    assert driver.calls == []


def test_not_supported_errors_are_notimplementederror_subclasses():
    assert issubclass(NotSupportedError, NotImplementedError)


# ---------------------------------------------------------------------------
# get_rna_seq_archs4
# ---------------------------------------------------------------------------

def test_get_rna_seq_archs4_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"gene_name": "TP53", "tissues": [{"tissue": "liver", "median_tpm": 12.5}]}'

    result = tools.get_rna_seq_archs4({"gene_name": "TP53", "K": 5}, driver)

    assert driver.last_args() == {"gene_name": "TP53", "K": 5}
    assert result["tissues"][0]["tissue"] == "liver"


def test_get_rna_seq_archs4_rejects_non_positive_k():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.get_rna_seq_archs4({"gene_name": "TP53", "K": 0}, driver)
    assert driver.calls == []


def test_get_rna_seq_archs4_rejects_missing_gene_name():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.get_rna_seq_archs4({}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# get_gene_set_enrichment_analysis_supported_database_list
# ---------------------------------------------------------------------------

def test_get_gene_set_enrichment_analysis_supported_database_list_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"databases": ["GO_Biological_Process_2021", "KEGG_2021_Human"]}'

    result = tools.get_gene_set_enrichment_analysis_supported_database_list({}, driver)

    assert result["databases"] == ["GO_Biological_Process_2021", "KEGG_2021_Human"]
    assert driver.last_args() == {}


# ---------------------------------------------------------------------------
# gene_set_enrichment_analysis
# ---------------------------------------------------------------------------

def test_gene_set_enrichment_analysis_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"results": [{"rank": 1, "path_name": "apoptosis"}]}'

    result = tools.gene_set_enrichment_analysis(
        {"genes": ["TP53", "BRCA1"], "top_k": 5, "database": "ontology"}, driver
    )

    assert driver.last_args()["genes"] == ["TP53", "BRCA1"]
    assert result["results"][0]["path_name"] == "apoptosis"
    assert "plot_requested_but_unsupported" not in result


def test_gene_set_enrichment_analysis_flags_unsupported_plot_request():
    driver = FakeSandboxDriver()
    driver.stdout = '{"results": []}'

    result = tools.gene_set_enrichment_analysis({"genes": ["TP53"], "plot": True}, driver)

    assert result["plot_requested_but_unsupported"] is True


def test_gene_set_enrichment_analysis_rejects_empty_gene_list():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.gene_set_enrichment_analysis({"genes": []}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_chromatin_interactions
# ---------------------------------------------------------------------------

def test_analyze_chromatin_interactions_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"n_significant_interactions": 3, "chromosomes": ["chr1"]}'

    result = tools.analyze_chromatin_interactions(
        {"hic_file_path": "data.cool", "regulatory_elements_bed": "reg.bed"}, driver
    )

    assert driver.last_args()["hic_file_path"] == "data.cool"
    assert result["n_significant_interactions"] == 3


def test_analyze_chromatin_interactions_rejects_absolute_path():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.analyze_chromatin_interactions(
            {"hic_file_path": "/etc/passwd", "regulatory_elements_bed": "reg.bed"}, driver
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_comparative_genomics_and_haplotypes
# ---------------------------------------------------------------------------

def test_analyze_comparative_genomics_and_haplotypes_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = (
        '{"samples": ["s1", "s2"], "variant_counts_per_sample": {"s1": 10, "s2": 12}, '
        '"shared_variant_count": 5, "unique_variant_counts_per_sample": {"s1": 5, "s2": 7}}'
    )

    result = tools.analyze_comparative_genomics_and_haplotypes(
        {"sample_fasta_files": ["s1.fasta", "s2.fasta"], "reference_genome_path": "ref.fasta"}, driver
    )

    assert driver.last_args()["sample_fasta_files"] == ["s1.fasta", "s2.fasta"]
    assert result["shared_variant_count"] == 5
    assert "random" not in driver.calls[-1][0]


def test_analyze_comparative_genomics_and_haplotypes_rejects_empty_sample_list():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.analyze_comparative_genomics_and_haplotypes(
            {"sample_fasta_files": [], "reference_genome_path": "ref.fasta"}, driver
        )
    assert driver.calls == []


def test_analyze_comparative_genomics_and_haplotypes_rejects_traversal_in_sample_list():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.analyze_comparative_genomics_and_haplotypes(
            {"sample_fasta_files": ["../../etc/passwd"], "reference_genome_path": "ref.fasta"}, driver
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# perform_chipseq_peak_calling_with_macs2
# ---------------------------------------------------------------------------

def test_perform_chipseq_peak_calling_with_macs2_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"n_peaks": 42, "peaks_preview": [], "q_value": 0.05}'

    result = tools.perform_chipseq_peak_calling_with_macs2(
        {"chip_seq_file": "chip.bam", "control_file": "input.bam"}, driver
    )

    assert driver.last_args() == {
        "chip_seq_file": "chip.bam", "control_file": "input.bam",
        "output_name": "macs2_output", "genome_size": "hs", "q_value": 0.05,
    }
    assert result["n_peaks"] == 42


def test_perform_chipseq_peak_calling_with_macs2_rejects_out_of_range_q_value():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.perform_chipseq_peak_calling_with_macs2(
            {"chip_seq_file": "chip.bam", "control_file": "input.bam", "q_value": 1.5}, driver
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# find_enriched_motifs_with_homer
# ---------------------------------------------------------------------------

def test_find_enriched_motifs_with_homer_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"n_de_novo_motifs": 2, "de_novo_motifs": [], "known_motifs": []}'

    result = tools.find_enriched_motifs_with_homer({"peak_file": "peaks.bed"}, driver)

    assert driver.last_args()["genome"] == "hg38"
    assert result["n_de_novo_motifs"] == 2


def test_find_enriched_motifs_with_homer_rejects_missing_peak_file():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.find_enriched_motifs_with_homer({}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_genomic_region_overlap
# ---------------------------------------------------------------------------

def test_analyze_genomic_region_overlap_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"sets": [], "pairwise_overlaps": []}'

    result = tools.analyze_genomic_region_overlap(
        {"region_sets": ["a.bed", "b.bed"]}, driver
    )

    assert driver.last_args()["region_sets"] == ["a.bed", "b.bed"]
    assert result["pairwise_overlaps"] == []


def test_analyze_genomic_region_overlap_rejects_empty_region_sets():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.analyze_genomic_region_overlap({"region_sets": []}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_atac_seq_differential_accessibility
# ---------------------------------------------------------------------------

def test_analyze_atac_seq_differential_accessibility_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = (
        '{"treatment_peaks": 100, "control_peaks": 80, '
        '"differential_treatment_enriched": 5, "differential_control_enriched": 2}'
    )

    result = tools.analyze_atac_seq_differential_accessibility(
        {"treatment_bam": "t.bam", "control_bam": "c.bam"}, driver
    )

    assert driver.last_args()["name_prefix"] == "atac"
    assert result["treatment_peaks"] == 100


def test_analyze_atac_seq_differential_accessibility_rejects_missing_control_bam():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.analyze_atac_seq_differential_accessibility({"treatment_bam": "t.bam"}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_ddr_network_in_cancer
# ---------------------------------------------------------------------------

def test_analyze_ddr_network_in_cancer_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = '{"n_ddr_genes_found": 10, "hub_genes": [], "network_density": 0.3}'

    result = tools.analyze_ddr_network_in_cancer(
        {"expression_data_path": "expr.csv", "mutation_data_path": "mut.csv"}, driver
    )

    assert driver.last_args()["expression_data_path"] == "expr.csv"
    assert result["network_density"] == 0.3


def test_analyze_ddr_network_in_cancer_rejects_missing_mutation_path():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.analyze_ddr_network_in_cancer({"expression_data_path": "expr.csv"}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# detect_and_annotate_somatic_mutations
# ---------------------------------------------------------------------------

def test_detect_and_annotate_somatic_mutations_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = (
        '{"output_prefix": "run1", "total_somatic_variants": 30, '
        '"variant_types": {"SNP": 25, "INS": 3, "DEL": 2}, "high_impact_variants": 4}'
    )

    result = tools.detect_and_annotate_somatic_mutations(
        {
            "tumor_bam": "tumor.bam", "normal_bam": "normal.bam",
            "reference_genome": "ref.fasta", "output_prefix": "run1",
        },
        driver,
    )

    assert driver.last_args()["snpeff_database"] == "GRCh38.105"
    assert result["total_somatic_variants"] == 30
    assert "shell=True" not in driver.calls[-1][0]


def test_detect_and_annotate_somatic_mutations_rejects_missing_output_prefix():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.detect_and_annotate_somatic_mutations(
            {"tumor_bam": "tumor.bam", "normal_bam": "normal.bam", "reference_genome": "ref.fasta"},
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# detect_and_characterize_structural_variations
# ---------------------------------------------------------------------------

def test_detect_and_characterize_structural_variations_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = (
        '{"total_svs": 7, "sv_counts_by_type": {"DEL": 4, "DUP": 3, "INV": 0, "BND": 0, "INS": 0}, '
        '"records_preview": [], "cosmic_position_matches": 0, "clinvar_position_matches": 0}'
    )

    result = tools.detect_and_characterize_structural_variations(
        {"bam_file_path": "sample.bam", "reference_genome_path": "ref.fasta", "output_dir": "out"},
        driver,
    )

    assert driver.last_args()["cosmic_db_path"] is None
    assert result["total_svs"] == 7
    assert "shell=True" not in driver.calls[-1][0]


def test_detect_and_characterize_structural_variations_rejects_missing_output_dir():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.detect_and_characterize_structural_variations(
            {"bam_file_path": "sample.bam", "reference_genome_path": "ref.fasta"}, driver
        )
    assert driver.calls == []


def test_detect_and_characterize_structural_variations_rejects_traversal_in_cosmic_db_path():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.detect_and_characterize_structural_variations(
            {
                "bam_file_path": "sample.bam", "reference_genome_path": "ref.fasta",
                "output_dir": "out", "cosmic_db_path": "../../etc/passwd",
            },
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# perform_gene_expression_nmf_analysis
# ---------------------------------------------------------------------------

def test_perform_gene_expression_nmf_analysis_round_trips_and_parses_result():
    driver = FakeSandboxDriver()
    driver.stdout = (
        '{"n_genes": 100, "n_samples": 20, "n_components": 5, "reconstruction_error": 1.23, '
        '"n_iterations": 200, "top_genes_per_metagene": {}, "sample_weights_preview": {}}'
    )

    result = tools.perform_gene_expression_nmf_analysis(
        {"expression_data_path": "expr.csv", "n_components": 5}, driver
    )

    assert driver.last_args()["random_state"] == 42
    assert result["n_components"] == 5


def test_perform_gene_expression_nmf_analysis_rejects_non_positive_n_components():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        tools.perform_gene_expression_nmf_analysis(
            {"expression_data_path": "expr.csv", "n_components": 0}, driver
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# register_single_cell_omics_tools
# ---------------------------------------------------------------------------

def test_register_single_cell_omics_tools_registers_all_18_tools():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    names = tools.register_single_cell_omics_tools(registry, driver)

    assert len(names) == 18
    assert set(names) == set(registry.registry.keys())
    for name in names:
        assert callable(registry.registry[name])


def test_registered_sync_tool_is_callable_through_the_registry_single_arg_shape():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()
    driver.stdout = '{"n_peaks": 1}'
    tools.register_single_cell_omics_tools(registry, driver)

    handler = registry.registry["perform_chipseq_peak_calling_with_macs2"]
    result = handler({"chip_seq_file": "chip.bam", "control_file": "input.bam"})

    assert result == {"n_peaks": 1}
