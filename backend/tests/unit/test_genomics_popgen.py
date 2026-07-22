"""Unit tests for the Genomics & population genetics action tools (Fase 5).

Per `_sandbox_tool_base.py`'s documented testing boundary, these tests
exercise argument validation + sandbox wiring via `FakeSandboxDriver`, never
the real scientific `script_body` logic (which needs biopython/msprime/
scipy/torch from the sandbox toolkit's own conda env, not this repo's
pytest venv)."""
import json

import pytest
from pydantic import ValidationError

from src.domain.services.path_guard import PathTraversalError
from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver
from src.infrastructure.tools.genomics_popgen import (
    analyze_cas9_mutation_outcomes,
    analyze_crispr_genome_editing,
    analyze_protein_phylogeny,
    bayesian_finemapping_with_deep_vi,
    fit_genomic_prediction_model,
    identify_transcription_factor_binding_sites,
    liftover_coordinates,
    perform_crispr_cas9_genome_editing,
    perform_pcr_and_gel_electrophoresis,
    register_genomics_popgen_tools,
    simulate_demographic_history,
)

ALL_TOOL_NAMES = {
    "liftover_coordinates",
    "bayesian_finemapping_with_deep_vi",
    "analyze_cas9_mutation_outcomes",
    "analyze_crispr_genome_editing",
    "perform_crispr_cas9_genome_editing",
    "simulate_demographic_history",
    "identify_transcription_factor_binding_sites",
    "fit_genomic_prediction_model",
    "perform_pcr_and_gel_electrophoresis",
    "analyze_protein_phylogeny",
}


# --- liftover_coordinates -------------------------------------------------


def test_liftover_coordinates_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"chromosome": "chr1", "position": 100099, "lifted": True})

    result = liftover_coordinates(
        {
            "chromosome": "chr1",
            "position": 100000,
            "input_format": "hg19",
            "output_format": "hg38",
            "data_path": "chain_files/hg19ToHg38.over.chain.gz",
        },
        driver,
    )

    assert result == {"chromosome": "chr1", "position": 100099, "lifted": True}
    assert driver.last_args() == {
        "chromosome": "chr1",
        "position": 100000,
        "input_format": "hg19",
        "output_format": "hg38",
        "data_path": "chain_files/hg19ToHg38.over.chain.gz",
    }


def test_liftover_coordinates_missing_required_field_raises_before_sandbox_call():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        liftover_coordinates({"position": 100000, "input_format": "hg19", "output_format": "hg38"}, driver)
    assert driver.calls == []


def test_liftover_coordinates_path_traversal_in_data_path_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        liftover_coordinates(
            {
                "chromosome": "chr1",
                "position": 1,
                "input_format": "hg19",
                "output_format": "hg38",
                "data_path": "../../etc/passwd",
            },
            driver,
        )
    assert driver.calls == []


# --- bayesian_finemapping_with_deep_vi ------------------------------------


def test_bayesian_finemapping_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"credible_set_indices": [0], "n_snps": 2})

    result = bayesian_finemapping_with_deep_vi(
        {
            "gwas_summary_path": "gwas/summary.csv",
            "ld_matrix": [[1.0, 0.2], [0.2, 1.0]],
            "n_iterations": 10,
            "learning_rate": 0.05,
            "hidden_dim": 8,
            "credible_threshold": 0.9,
        },
        driver,
    )

    assert result == {"credible_set_indices": [0], "n_snps": 2}
    args = driver.last_args()
    assert args["gwas_summary_path"] == "gwas/summary.csv"
    assert args["ld_matrix"] == [[1.0, 0.2], [0.2, 1.0]]
    assert args["n_iterations"] == 10
    assert args["hidden_dim"] == 8


def test_bayesian_finemapping_non_square_ld_matrix_raises_before_sandbox_call():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        bayesian_finemapping_with_deep_vi(
            {"gwas_summary_path": "gwas/summary.csv", "ld_matrix": [[1.0, 0.2]]}, driver
        )
    assert driver.calls == []


def test_bayesian_finemapping_credible_threshold_out_of_range_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        bayesian_finemapping_with_deep_vi(
            {
                "gwas_summary_path": "gwas/summary.csv",
                "ld_matrix": [[1.0, 0.0], [0.0, 1.0]],
                "credible_threshold": 1.5,
            },
            driver,
        )
    assert driver.calls == []


# --- analyze_cas9_mutation_outcomes ---------------------------------------


def test_analyze_cas9_mutation_outcomes_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"mutation_type_counts": {"deletion": 1}})

    result = analyze_cas9_mutation_outcomes(
        {
            "reference_sequences": {"g1": "ATGCATGC"},
            "edited_sequences": {"g1": "ATGCATG"},
            "cell_line_info": {"line": "HEK293"},
            "output_prefix": "cas9_test",
        },
        driver,
    )

    assert result == {"mutation_type_counts": {"deletion": 1}}
    args = driver.last_args()
    assert args["reference_sequences"] == {"g1": "ATGCATGC"}
    assert args["edited_sequences"] == {"g1": "ATGCATG"}
    assert args["output_prefix"] == "cas9_test"


def test_analyze_cas9_mutation_outcomes_empty_reference_sequences_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_cas9_mutation_outcomes({"reference_sequences": {}, "edited_sequences": {"g1": "A"}}, driver)
    assert driver.calls == []


# --- analyze_crispr_genome_editing ----------------------------------------


def test_analyze_crispr_genome_editing_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"edit_outcome": "nhej_indel"})

    result = analyze_crispr_genome_editing(
        {
            "original_sequence": "ATGCATGCATGCTGG",
            "edited_sequence": "ATGCATGCATGTGG",
            "guide_rna": "ATGCATGCATGC",
            "repair_template": None,
        },
        driver,
    )

    assert result == {"edit_outcome": "nhej_indel"}
    args = driver.last_args()
    assert args["guide_rna"] == "ATGCATGCATGC"
    assert args["repair_template"] is None


def test_analyze_crispr_genome_editing_empty_guide_rna_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_crispr_genome_editing(
            {"original_sequence": "ATGC", "edited_sequence": "ATGC", "guide_rna": ""}, driver
        )
    assert driver.calls == []


# --- perform_crispr_cas9_genome_editing -----------------------------------


def test_perform_crispr_cas9_genome_editing_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"guides": []})

    result = perform_crispr_cas9_genome_editing(
        {
            "guide_rna_sequences": ["ATGCATGCATGC"],
            "target_genomic_loci": "TTTTATGCATGCATGCAGGTTTT",
            "cell_tissue_type": "HEK293",
        },
        driver,
    )

    assert result == {"guides": []}
    args = driver.last_args()
    assert args["guide_rna_sequences"] == ["ATGCATGCATGC"]
    assert args["cell_tissue_type"] == "HEK293"


def test_perform_crispr_cas9_genome_editing_empty_guide_list_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        perform_crispr_cas9_genome_editing(
            {"guide_rna_sequences": [], "target_genomic_loci": "ATGC", "cell_tissue_type": "HEK293"}, driver
        )
    assert driver.calls == []


# --- simulate_demographic_history -----------------------------------------


def test_simulate_demographic_history_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"num_trees": 12, "num_mutations": 34})

    result = simulate_demographic_history(
        {
            "num_samples": 5,
            "sequence_length": 1000,
            "demographic_model": "constant",
            "coalescent_model": "kingman",
            "output_file": "sim/out.vcf",
        },
        driver,
    )

    assert result == {"num_trees": 12, "num_mutations": 34}
    args = driver.last_args()
    assert args["num_samples"] == 5
    assert args["output_file"] == "sim/out.vcf"
    assert args["coalescent_model"] == "kingman"


def test_simulate_demographic_history_beta_coalescent_without_param_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_demographic_history({"coalescent_model": "beta"}, driver)
    assert driver.calls == []


def test_simulate_demographic_history_unsupported_demographic_model_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_demographic_history({"demographic_model": "not_a_real_model"}, driver)
    assert driver.calls == []


# --- identify_transcription_factor_binding_sites --------------------------


def test_identify_tf_binding_sites_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"num_matches": 1, "tf_name": "SP1"})

    result = identify_transcription_factor_binding_sites(
        {"sequence": "ACGTACGTGGGGCGGGGCACGT", "tf_name": "SP1", "threshold": 0.5}, driver
    )

    assert result == {"num_matches": 1, "tf_name": "SP1"}
    args = driver.last_args()
    assert args["sequence"] == "ACGTACGTGGGGCGGGGCACGT"
    assert args["tf_name"] == "SP1"
    assert args["threshold"] == 0.5
    assert "SP1" in args["known_tf_consensus"]
    assert args["output_file"] is None


def test_identify_tf_binding_sites_threshold_out_of_range_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        identify_transcription_factor_binding_sites(
            {"sequence": "ACGT", "tf_name": "SP1", "threshold": 1.5}, driver
        )
    assert driver.calls == []


def test_identify_tf_binding_sites_empty_sequence_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        identify_transcription_factor_binding_sites({"sequence": "", "tf_name": "SP1"}, driver)
    assert driver.calls == []


# --- fit_genomic_prediction_model -----------------------------------------


def test_fit_genomic_prediction_model_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"heritability_estimate": 0.42})

    result = fit_genomic_prediction_model(
        {
            "genotypes": [[0, 1, 2], [1, 1, 0], [2, 0, 1], [0, 0, 2]],
            "phenotypes": [1.2, 0.5, 2.1, 0.3],
            "model_type": "additive",
            "output_file": "geno/out.csv",
        },
        driver,
    )

    assert result == {"heritability_estimate": 0.42}
    args = driver.last_args()
    assert args["genotypes"] == [[0, 1, 2], [1, 1, 0], [2, 0, 1], [0, 0, 2]]
    assert args["phenotypes"] == [1.2, 0.5, 2.1, 0.3]
    assert args["output_file"] == "geno/out.csv"


def test_fit_genomic_prediction_model_mismatched_phenotype_length_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        fit_genomic_prediction_model(
            {"genotypes": [[0, 1], [1, 1]], "phenotypes": [1.0]}, driver
        )
    assert driver.calls == []


def test_fit_genomic_prediction_model_unsupported_model_type_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        fit_genomic_prediction_model(
            {"genotypes": [[0, 1], [1, 1]], "phenotypes": [1.0, 2.0], "model_type": "bogus"}, driver
        )
    assert driver.calls == []


# --- perform_pcr_and_gel_electrophoresis ----------------------------------


def test_perform_pcr_and_gel_electrophoresis_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"amplicon_length": 8})

    result = perform_pcr_and_gel_electrophoresis(
        {
            "genomic_dna": "ATGCATGCATGCATGCATGCATGC",
            "target_region": (2, 10),
            "output_prefix": "pcr_test",
        },
        driver,
    )

    assert result == {"amplicon_length": 8}
    args = driver.last_args()
    assert args["genomic_dna"] == "ATGCATGCATGCATGCATGCATGC"
    assert args["target_region"] == [2, 10]
    assert args["output_prefix"] == "pcr_test"


def test_perform_pcr_and_gel_electrophoresis_no_amplification_strategy_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        perform_pcr_and_gel_electrophoresis({"genomic_dna": "ATGCATGCATGC"}, driver)
    assert driver.calls == []


# --- analyze_protein_phylogeny --------------------------------------------


def test_analyze_protein_phylogeny_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"newick_tree": "(seq1,seq2);"})

    result = analyze_protein_phylogeny(
        {
            "fasta_sequences": ">seq1\nMKV\n>seq2\nMKA\n",
            "output_dir": "phylo_out",
            "alignment_method": "mafft",
            "tree_method": "fasttree",
        },
        driver,
    )

    assert result == {"newick_tree": "(seq1,seq2);"}
    args = driver.last_args()
    assert args["fasta_sequences"] == ">seq1\nMKV\n>seq2\nMKA\n"
    assert args["output_dir"] == "phylo_out"
    assert args["alignment_method"] == "mafft"


def test_analyze_protein_phylogeny_unsupported_alignment_method_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_protein_phylogeny({"fasta_sequences": ">s\nMK\n", "alignment_method": "bogus"}, driver)
    assert driver.calls == []


def test_analyze_protein_phylogeny_empty_fasta_sequences_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_protein_phylogeny({"fasta_sequences": ""}, driver)
    assert driver.calls == []


# --- registration -----------------------------------------------------------


def test_register_genomics_popgen_tools_registers_all_ten_tool_names():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    registered_names = register_genomics_popgen_tools(registry, driver)

    assert set(registered_names) == ALL_TOOL_NAMES
    for name in ALL_TOOL_NAMES:
        assert name in registry.registry
        assert callable(registry.registry[name])


@pytest.mark.asyncio
async def test_registered_handler_routes_through_registry_and_calls_sandbox():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"lifted": True})
    register_genomics_popgen_tools(registry, driver)

    raw_result = await registry.route(
        "liftover_coordinates",
        {
            "chromosome": "chr1",
            "position": 12345,
            "input_format": "hg19",
            "output_format": "hg38",
            "data_path": "chain_files/hg19ToHg38.over.chain.gz",
        },
    )

    assert json.loads(raw_result) == {"lifted": True}
    assert len(driver.calls) == 1
