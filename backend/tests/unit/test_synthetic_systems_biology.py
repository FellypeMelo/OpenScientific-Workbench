"""Unit tests for the Synthetic biology & systems biology action tools
(Fase 5).

Per `_sandbox_tool_base.py`'s documented testing boundary, these tests
exercise argument validation + sandbox wiring via `FakeSandboxDriver`, never
the real scientific `script_body` logic (which needs biopython/scipy/cobra/
libsbml from the sandbox toolkit's own conda env, not this repo's pytest
venv)."""
import json

import pytest
from pydantic import ValidationError

from src.domain.services.path_guard import PathTraversalError
from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver
from src.infrastructure.tools.synthetic_systems_biology import (
    analyze_barcode_sequencing_data,
    analyze_bifurcation_diagram,
    analyze_in_vitro_drug_release_kinetics,
    compare_protein_structures,
    create_biochemical_network_sbml_model,
    engineer_bacterial_genome_for_therapeutic_delivery,
    identify_fas_functional_domains,
    model_protein_dimerization_network,
    optimize_codons_for_heterologous_expression,
    perform_flux_balance_analysis,
    register_synthetic_systems_biology_tools,
    simulate_gene_circuit_with_growth_feedback,
    simulate_metabolic_network_perturbation,
    simulate_protein_signaling_network,
    simulate_renin_angiotensin_system_dynamics,
    simulate_whole_cell_ode_model,
)

ALL_TOOL_NAMES = {
    "engineer_bacterial_genome_for_therapeutic_delivery",
    "analyze_barcode_sequencing_data",
    "analyze_bifurcation_diagram",
    "create_biochemical_network_sbml_model",
    "optimize_codons_for_heterologous_expression",
    "simulate_gene_circuit_with_growth_feedback",
    "identify_fas_functional_domains",
    "perform_flux_balance_analysis",
    "model_protein_dimerization_network",
    "simulate_metabolic_network_perturbation",
    "simulate_protein_signaling_network",
    "compare_protein_structures",
    "simulate_renin_angiotensin_system_dynamics",
    "simulate_whole_cell_ode_model",
    "analyze_in_vitro_drug_release_kinetics",
}


# --- engineer_bacterial_genome_for_therapeutic_delivery --------------------


def test_engineer_bacterial_genome_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"genome_length_after": 120})

    result = engineer_bacterial_genome_for_therapeutic_delivery(
        {
            "bacterial_genome_file": "genomes/ecoli.fasta",
            "genetic_parts": {
                "promoters": ["TTGACA"],
                "genes": ["ATGAAATAA"],
                "terminators": ["TTTTTT"],
                "cargo": [],
                "insertion_position": 10,
            },
        },
        driver,
    )

    assert result == {"genome_length_after": 120}
    args = driver.last_args()
    assert args["bacterial_genome_file"] == "genomes/ecoli.fasta"
    assert args["genetic_parts"]["promoters"] == ["TTGACA"]
    assert args["genetic_parts"]["insertion_position"] == 10


def test_engineer_bacterial_genome_no_genes_or_cargo_raises_before_sandbox_call():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        engineer_bacterial_genome_for_therapeutic_delivery(
            {
                "bacterial_genome_file": "genomes/ecoli.fasta",
                "genetic_parts": {"promoters": ["TTGACA"], "terminators": ["TTTTTT"]},
            },
            driver,
        )
    assert driver.calls == []


def test_engineer_bacterial_genome_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        engineer_bacterial_genome_for_therapeutic_delivery(
            {
                "bacterial_genome_file": "../../etc/passwd",
                "genetic_parts": {"genes": ["ATGAAATAA"]},
            },
            driver,
        )
    assert driver.calls == []


def test_engineer_bacterial_genome_invalid_bases_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        engineer_bacterial_genome_for_therapeutic_delivery(
            {
                "bacterial_genome_file": "genomes/ecoli.fasta",
                "genetic_parts": {"genes": ["ATGXYZ"]},
            },
            driver,
        )
    assert driver.calls == []


# --- analyze_barcode_sequencing_data ----------------------------------------


def test_analyze_barcode_sequencing_data_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"n_unique_barcodes_passing_min_count": 3})

    result = analyze_barcode_sequencing_data(
        {
            "input_file": "reads/barcodes.fasta",
            "barcode_pattern": "NNNNNNNNNNNNNNNNNNNN",
            "min_count": 2,
            "output_dir": "results/barcodes",
        },
        driver,
    )

    assert result == {"n_unique_barcodes_passing_min_count": 3}
    args = driver.last_args()
    assert args["input_file"] == "reads/barcodes.fasta"
    assert args["min_count"] == 2
    assert args["output_dir"] == "results/barcodes"


def test_analyze_barcode_sequencing_data_no_extraction_strategy_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_barcode_sequencing_data({"input_file": "reads/barcodes.fasta"}, driver)
    assert driver.calls == []


def test_analyze_barcode_sequencing_data_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_barcode_sequencing_data(
            {"input_file": "/etc/passwd", "barcode_pattern": "NNNN"}, driver
        )
    assert driver.calls == []


# --- analyze_bifurcation_diagram --------------------------------------------


def test_analyze_bifurcation_diagram_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"branch_counts": [1, 2]})

    result = analyze_bifurcation_diagram(
        {
            "time_series_data": [[0.1, 0.5, 0.2, 0.6], [0.3, 0.7, 0.2, 0.8]],
            "parameter_values": [1.0, 2.0],
            "system_name": "Logistic Map",
            "output_dir": "bifurcation_out",
        },
        driver,
    )

    assert result == {"branch_counts": [1, 2]}
    args = driver.last_args()
    assert args["parameter_values"] == [1.0, 2.0]
    assert args["system_name"] == "Logistic Map"


def test_analyze_bifurcation_diagram_mismatched_lengths_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_bifurcation_diagram(
            {"time_series_data": [[0.1, 0.2, 0.3, 0.4]], "parameter_values": [1.0, 2.0]}, driver
        )
    assert driver.calls == []


def test_analyze_bifurcation_diagram_too_short_series_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_bifurcation_diagram(
            {"time_series_data": [[0.1, 0.2]], "parameter_values": [1.0]}, driver
        )
    assert driver.calls == []


# --- create_biochemical_network_sbml_model ----------------------------------


def test_create_biochemical_network_sbml_model_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"n_reactions": 1})

    result = create_biochemical_network_sbml_model(
        {
            "reaction_network": [
                {"id": "R1", "substrates": {"A": 1}, "products": {"B": 1}, "reversible": False}
            ],
            "kinetic_parameters": {"R1": {"k_forward": 0.5}},
            "output_file": "models/biochem.xml",
        },
        driver,
    )

    assert result == {"n_reactions": 1}
    args = driver.last_args()
    assert args["reaction_network"][0]["id"] == "R1"
    assert args["output_file"] == "models/biochem.xml"


def test_create_biochemical_network_sbml_model_empty_reaction_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        create_biochemical_network_sbml_model(
            {"reaction_network": [{"id": "R1", "substrates": {}, "products": {}}]}, driver
        )
    assert driver.calls == []


def test_create_biochemical_network_sbml_model_empty_network_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        create_biochemical_network_sbml_model({"reaction_network": []}, driver)
    assert driver.calls == []


# --- optimize_codons_for_heterologous_expression ----------------------------


def test_optimize_codons_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"optimized_cai": 0.9})

    result = optimize_codons_for_heterologous_expression(
        {
            "target_sequence": "atgaaataa",
            "host_codon_usage": {"ATG": 1.0, "AAA": 0.8, "AAG": 0.2, "TAA": 0.6, "TAG": 0.4},
        },
        driver,
    )

    assert result == {"optimized_cai": 0.9}
    args = driver.last_args()
    assert args["target_sequence"] == "ATGAAATAA"
    assert args["host_codon_usage"]["ATG"] == 1.0


def test_optimize_codons_non_multiple_of_three_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        optimize_codons_for_heterologous_expression(
            {"target_sequence": "ATGAA", "host_codon_usage": {"ATG": 1.0}}, driver
        )
    assert driver.calls == []


def test_optimize_codons_empty_usage_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        optimize_codons_for_heterologous_expression(
            {"target_sequence": "ATGAAATAA", "host_codon_usage": {}}, driver
        )
    assert driver.calls == []


# --- simulate_gene_circuit_with_growth_feedback -----------------------------


def test_simulate_gene_circuit_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"final_growth_rate": 0.5})

    result = simulate_gene_circuit_with_growth_feedback(
        {
            "circuit_topology": [[0.0, 1.0], [-1.0, 0.0]],
            "kinetic_params": {"basal_rates": [0.1, 0.1], "initial_conditions": [0.0, 0.0]},
            "growth_params": {"mu_max": 1.0, "burden_K": 500.0},
            "simulation_time": 50,
            "time_points": 200,
        },
        driver,
    )

    assert result == {"final_growth_rate": 0.5}
    args = driver.last_args()
    assert args["circuit_topology"] == [[0.0, 1.0], [-1.0, 0.0]]
    assert args["simulation_time"] == 50
    assert args["time_points"] == 200


def test_simulate_gene_circuit_non_square_topology_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_gene_circuit_with_growth_feedback(
            {
                "circuit_topology": [[0.0, 1.0]],
                "kinetic_params": {},
                "growth_params": {},
            },
            driver,
        )
    assert driver.calls == []


# --- identify_fas_functional_domains ----------------------------------------


def test_identify_fas_functional_domains_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"protein_length": 10})

    result = identify_fas_functional_domains(
        {"sequence": "mgssykdrsl", "sequence_type": "protein", "output_file": "fas/report.txt"},
        driver,
    )

    assert result == {"protein_length": 10}
    args = driver.last_args()
    assert args["sequence"] == "MGSSYKDRSL"
    assert args["output_file"] == "fas/report.txt"
    assert "MAT_AT" in args["fas_domain_motifs"]


def test_identify_fas_functional_domains_empty_sequence_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        identify_fas_functional_domains({"sequence": ""}, driver)
    assert driver.calls == []


def test_identify_fas_functional_domains_invalid_sequence_type_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        identify_fas_functional_domains({"sequence": "MGSS", "sequence_type": "rna"}, driver)
    assert driver.calls == []


# --- perform_flux_balance_analysis ------------------------------------------


def test_perform_flux_balance_analysis_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"status": "optimal"})

    result = perform_flux_balance_analysis(
        {
            "model_file": "models/ecoli_core.xml",
            "constraints": {"EX_glc__D_e": [-10.0, 0.0]},
            "objective_reaction": "BIOMASS_Ecoli_core",
            "output_file": "fba/results.csv",
        },
        driver,
    )

    assert result == {"status": "optimal"}
    args = driver.last_args()
    assert args["model_file"] == "models/ecoli_core.xml"
    assert args["constraints"] == {"EX_glc__D_e": [-10.0, 0.0]}
    assert args["objective_reaction"] == "BIOMASS_Ecoli_core"


def test_perform_flux_balance_analysis_malformed_constraint_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        perform_flux_balance_analysis(
            {"model_file": "models/ecoli_core.xml", "constraints": {"EX_glc__D_e": [-10.0]}},
            driver,
        )
    assert driver.calls == []


def test_perform_flux_balance_analysis_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        perform_flux_balance_analysis({"model_file": "C:\\Windows\\model.xml"}, driver)
    assert driver.calls == []


# --- model_protein_dimerization_network -------------------------------------


def test_model_protein_dimerization_network_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"converged": True})

    result = model_protein_dimerization_network(
        {
            "monomer_concentrations": {"A": 10.0, "B": 5.0},
            "dimerization_affinities": {"A-B": 1.0},
            "network_topology": [["A", "B"]],
        },
        driver,
    )

    assert result == {"converged": True}
    args = driver.last_args()
    assert args["monomer_concentrations"] == {"A": 10.0, "B": 5.0}
    assert args["network_topology"] == [["A", "B"]]


def test_model_protein_dimerization_network_empty_concentrations_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        model_protein_dimerization_network(
            {
                "monomer_concentrations": {},
                "dimerization_affinities": {"A-B": 1.0},
                "network_topology": [["A", "B"]],
            },
            driver,
        )
    assert driver.calls == []


def test_model_protein_dimerization_network_malformed_pair_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        model_protein_dimerization_network(
            {
                "monomer_concentrations": {"A": 10.0},
                "dimerization_affinities": {"A-B": 1.0},
                "network_topology": [["A", "B", "C"]],
            },
            driver,
        )
    assert driver.calls == []


# --- simulate_metabolic_network_perturbation --------------------------------


def test_simulate_metabolic_network_perturbation_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"perturbation_time": 10.0})

    result = simulate_metabolic_network_perturbation(
        {
            "model_file": "models/kinetic_network.json",
            "initial_concentrations": {"A": 1.0, "B": 0.0},
            "perturbation_params": {
                "perturbation_time": 10.0,
                "rate_multipliers": {"0": {"k_forward": 0.5}},
            },
            "simulation_time": 50,
            "time_points": 100,
        },
        driver,
    )

    assert result == {"perturbation_time": 10.0}
    args = driver.last_args()
    assert args["model_file"] == "models/kinetic_network.json"
    assert args["initial_concentrations"] == {"A": 1.0, "B": 0.0}
    assert args["perturbation_params"]["perturbation_time"] == 10.0


def test_simulate_metabolic_network_perturbation_empty_concentrations_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_metabolic_network_perturbation(
            {"model_file": "models/kinetic_network.json", "initial_concentrations": {}}, driver
        )
    assert driver.calls == []


def test_simulate_metabolic_network_perturbation_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        simulate_metabolic_network_perturbation(
            {"model_file": "../secrets.json", "initial_concentrations": {"A": 1.0}}, driver
        )
    assert driver.calls == []


# --- simulate_protein_signaling_network -------------------------------------


def test_simulate_protein_signaling_network_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"species_names": ["A", "B"]})

    result = simulate_protein_signaling_network(
        {
            "network_structure": {
                "species": ["A", "B"],
                "edges": [{"source": "A", "target": "B", "type": "activation"}],
            },
            "reaction_params": {"A->B": {"n": 2, "EC50": 0.5}},
            "species_params": {"A": {"initial_value": 1.0, "tau": 1.0}},
            "simulation_time": 20,
            "time_points": 50,
        },
        driver,
    )

    assert result == {"species_names": ["A", "B"]}
    args = driver.last_args()
    assert args["network_structure"]["species"] == ["A", "B"]
    assert args["simulation_time"] == 20


def test_simulate_protein_signaling_network_missing_species_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_protein_signaling_network({"network_structure": {"edges": []}}, driver)
    assert driver.calls == []


# --- compare_protein_structures ---------------------------------------------


def test_compare_protein_structures_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"rmsd": 1.23})

    result = compare_protein_structures(
        {
            "pdb_file1": "structures/protein1.pdb",
            "pdb_file2": "structures/protein2.pdb",
            "chain_id1": "A",
            "chain_id2": "B",
            "output_prefix": "compare_out",
        },
        driver,
    )

    assert result == {"rmsd": 1.23}
    args = driver.last_args()
    assert args["pdb_file1"] == "structures/protein1.pdb"
    assert args["chain_id2"] == "B"


def test_compare_protein_structures_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        compare_protein_structures(
            {"pdb_file1": "../../etc/passwd", "pdb_file2": "structures/protein2.pdb"}, driver
        )
    assert driver.calls == []


def test_compare_protein_structures_missing_required_field_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        compare_protein_structures({"pdb_file1": "structures/protein1.pdb"}, driver)
    assert driver.calls == []


# --- simulate_renin_angiotensin_system_dynamics -----------------------------


def test_simulate_ras_dynamics_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"species_names": ["Renin", "AGT", "AngI", "AngII"]})

    result = simulate_renin_angiotensin_system_dynamics(
        {
            "initial_concentrations": {"Renin": 1.0, "AGT": 10.0, "AngI": 0.0, "AngII": 0.0},
            "rate_constants": {"k1": 0.02, "k2": 0.4},
            "feedback_params": {"K_feedback": 2.0},
            "simulation_time": 24,
            "time_points": 50,
        },
        driver,
    )

    assert result == {"species_names": ["Renin", "AGT", "AngI", "AngII"]}
    args = driver.last_args()
    assert args["initial_concentrations"]["Renin"] == 1.0
    assert args["simulation_time"] == 24


def test_simulate_ras_dynamics_missing_required_species_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_renin_angiotensin_system_dynamics(
            {"initial_concentrations": {"Renin": 1.0}}, driver
        )
    assert driver.calls == []


# --- simulate_whole_cell_ode_model -------------------------------------------


def test_simulate_whole_cell_ode_model_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"success": True, "t": [0.0, 1.0]})

    result = simulate_whole_cell_ode_model(
        {
            "initial_conditions": [1.0, 0.0, 0.0],
            "parameters": {"rate_constants": [0.1, 0.2, 0.3]},
            "ode_function": "mass_action_chain",
            "time_span": (0.0, 10.0),
            "time_points": 100,
            "method": "LSODA",
        },
        driver,
    )

    assert result == {"success": True, "t": [0.0, 1.0]}
    args = driver.last_args()
    assert args["initial_conditions"] == [1.0, 0.0, 0.0]
    assert args["time_span"] == [0.0, 10.0]
    assert args["ode_function"] == "mass_action_chain"


def test_simulate_whole_cell_ode_model_defaults_to_mass_action_chain():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"success": True})

    simulate_whole_cell_ode_model({"initial_conditions": [1.0, 0.0]}, driver)

    args = driver.last_args()
    assert args["ode_function"] == "mass_action_chain"


def test_simulate_whole_cell_ode_model_unsupported_ode_function_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_whole_cell_ode_model(
            {"initial_conditions": [1.0], "ode_function": "not_a_real_model"}, driver
        )
    assert driver.calls == []


def test_simulate_whole_cell_ode_model_unsupported_method_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_whole_cell_ode_model(
            {"initial_conditions": [1.0], "method": "not_a_real_method"}, driver
        )
    assert driver.calls == []


def test_simulate_whole_cell_ode_model_backwards_time_span_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_whole_cell_ode_model(
            {"initial_conditions": [1.0], "time_span": (10.0, 0.0)}, driver
        )
    assert driver.calls == []


def test_simulate_whole_cell_ode_model_empty_initial_conditions_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_whole_cell_ode_model({"initial_conditions": []}, driver)
    assert driver.calls == []


# --- analyze_in_vitro_drug_release_kinetics ---------------------------------


def test_analyze_in_vitro_drug_release_kinetics_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"best_model": "higuchi"})

    result = analyze_in_vitro_drug_release_kinetics(
        {
            "time_points": [0, 1, 2, 4, 8],
            "concentration_data": [0, 10, 14, 20, 28],
            "drug_name": "TestDrug",
            "total_drug_loaded": 100.0,
            "output_dir": "release_out",
        },
        driver,
    )

    assert result == {"best_model": "higuchi"}
    args = driver.last_args()
    assert args["time_points"] == [0, 1, 2, 4, 8]
    assert args["drug_name"] == "TestDrug"
    assert args["output_dir"] == "release_out"


def test_analyze_in_vitro_drug_release_kinetics_mismatched_lengths_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_in_vitro_drug_release_kinetics(
            {"time_points": [0, 1, 2], "concentration_data": [0, 1]}, driver
        )
    assert driver.calls == []


def test_analyze_in_vitro_drug_release_kinetics_too_few_points_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_in_vitro_drug_release_kinetics(
            {"time_points": [0, 1], "concentration_data": [0, 1]}, driver
        )
    assert driver.calls == []


# --- registration -----------------------------------------------------------


def test_register_synthetic_systems_biology_tools_registers_all_tool_names():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    registered_names = register_synthetic_systems_biology_tools(registry, driver)

    assert set(registered_names) == ALL_TOOL_NAMES
    for name in ALL_TOOL_NAMES:
        assert name in registry.registry
        assert callable(registry.registry[name])


@pytest.mark.asyncio
async def test_registered_handler_routes_through_registry_and_calls_sandbox():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"success": True})
    register_synthetic_systems_biology_tools(registry, driver)

    raw_result = await registry.route(
        "simulate_whole_cell_ode_model",
        {"initial_conditions": [1.0, 0.0], "parameters": {"rate_constants": [0.1, 0.2]}},
    )

    assert json.loads(raw_result) == {"success": True}
    assert len(driver.calls) == 1
