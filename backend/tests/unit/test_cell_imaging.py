"""Unit tests for the "Cell biology & imaging" action tools
(`src/infrastructure/tools/cell_imaging.py`, Fase 5).

Per `_sandbox_tool_base.py`'s documented testing boundary (this repo's own
pytest venv has no scikit-image/opencv/trackpy/flowio -- those only exist in
the sandbox toolkit's own conda env), every test here verifies the WIRING and
VALIDATION layer via `FakeSandboxDriver`: valid arguments round-trip into the
sandbox call, a Pydantic `ValidationError` is raised for bad/missing required
arguments BEFORE `run_in_sandbox` is ever invoked, and the handler correctly
returns a canned `FakeSandboxDriver` result. None of these tests execute a
real `script_body` or assert on real scientific/numeric correctness.
"""
import json

import pytest
from pydantic import ValidationError

from src.domain.services.path_guard import PathTraversalError
from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver
from src.infrastructure.tools.cell_imaging import (
    analyze_calcium_imaging_data,
    analyze_cell_migration_metrics,
    analyze_cell_morphology_and_cytoskeleton,
    analyze_cell_senescence_and_apoptosis,
    analyze_cfse_cell_proliferation,
    analyze_flow_cytometry_immunophenotyping,
    analyze_mitochondrial_morphology_and_potential,
    analyze_myofiber_morphology,
    analyze_tissue_deformation_flow,
    estimate_cell_cycle_phase_durations,
    perform_facs_cell_sorting,
    predict_protein_disorder_regions,
    quantify_and_cluster_cell_motility,
    quantify_cell_cycle_phases_from_microscopy,
    register_cell_imaging_tools,
)


def _driver(stdout_obj):
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps(stdout_obj)
    return driver


# --- analyze_cell_migration_metrics ---------------------------------------


def test_analyze_cell_migration_metrics_valid_args_round_trip():
    driver = _driver({"n_tracks": 3})
    result = analyze_cell_migration_metrics(
        {
            "image_sequence_path": "frames/seq1",
            "pixel_size_um": 0.5,
            "time_interval_min": 2.0,
            "min_track_length": 5,
            "output_dir": "out1",
        },
        driver,
    )
    assert result == {"n_tracks": 3}
    args = driver.last_args()
    assert args["image_sequence_path"] == "frames/seq1"
    assert args["pixel_size_um"] == 0.5
    assert args["min_track_length"] == 5
    assert args["output_dir"] == "out1"


def test_analyze_cell_migration_metrics_missing_required_arg_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_cell_migration_metrics({"pixel_size_um": 1.0}, driver)
    assert driver.calls == []


def test_analyze_cell_migration_metrics_rejects_path_traversal():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_cell_migration_metrics(
            {"image_sequence_path": "../../etc/passwd"}, driver
        )
    assert driver.calls == []


# --- analyze_calcium_imaging_data -----------------------------------------


def test_analyze_calcium_imaging_data_valid_args_round_trip():
    driver = _driver({"n_cells": 7})
    result = analyze_calcium_imaging_data(
        {"image_stack_path": "stacks/ca1.tif", "output_dir": "out2"}, driver
    )
    assert result == {"n_cells": 7}
    assert driver.last_args() == {"image_stack_path": "stacks/ca1.tif", "output_dir": "out2"}


def test_analyze_calcium_imaging_data_missing_required_arg_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_calcium_imaging_data({}, driver)
    assert driver.calls == []


def test_analyze_calcium_imaging_data_rejects_absolute_path():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_calcium_imaging_data({"image_stack_path": "C:\\Windows\\evil.tif"}, driver)
    assert driver.calls == []


# --- analyze_myofiber_morphology ------------------------------------------


def test_analyze_myofiber_morphology_valid_args_round_trip():
    driver = _driver({"n_fibers": 12})
    result = analyze_myofiber_morphology(
        {
            "image_path": "img/myo.tif",
            "nuclei_channel": 0,
            "myofiber_channel": 1,
            "threshold_method": "otsu",
            "output_dir": "out3",
        },
        driver,
    )
    assert result == {"n_fibers": 12}
    args = driver.last_args()
    assert args["nuclei_channel"] == 0
    assert args["threshold_method"] == "otsu"


def test_analyze_myofiber_morphology_invalid_threshold_method_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_myofiber_morphology(
            {"image_path": "img/myo.tif", "threshold_method": "bogus"}, driver
        )
    assert driver.calls == []


# --- quantify_cell_cycle_phases_from_microscopy ----------------------------


def test_quantify_cell_cycle_phases_valid_args_round_trip():
    driver = _driver({"total_cells": 40})
    result = quantify_cell_cycle_phases_from_microscopy(
        {"image_paths": ["a.tif", "b.tif"], "output_dir": "out4"}, driver
    )
    assert result == {"total_cells": 40}
    assert driver.last_args()["image_paths"] == ["a.tif", "b.tif"]


def test_quantify_cell_cycle_phases_empty_paths_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        quantify_cell_cycle_phases_from_microscopy({"image_paths": []}, driver)
    assert driver.calls == []


def test_quantify_cell_cycle_phases_rejects_traversal_in_any_path():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        quantify_cell_cycle_phases_from_microscopy(
            {"image_paths": ["good.tif", "../bad.tif"]}, driver
        )
    assert driver.calls == []


# --- quantify_and_cluster_cell_motility ------------------------------------


def test_quantify_and_cluster_cell_motility_valid_args_round_trip():
    driver = _driver({"n_tracks": 5, "n_clusters": 2})
    result = quantify_and_cluster_cell_motility(
        {"image_sequence_path": "frames/seq2", "output_dir": "out5", "num_clusters": 2}, driver
    )
    assert result == {"n_tracks": 5, "n_clusters": 2}
    assert driver.last_args()["num_clusters"] == 2


def test_quantify_and_cluster_cell_motility_zero_clusters_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        quantify_and_cluster_cell_motility(
            {"image_sequence_path": "frames/seq2", "num_clusters": 0}, driver
        )
    assert driver.calls == []


# --- analyze_mitochondrial_morphology_and_potential ------------------------


def test_analyze_mitochondrial_morphology_valid_args_round_trip():
    driver = _driver({"n_mitochondria": 9})
    result = analyze_mitochondrial_morphology_and_potential(
        {
            "morphology_image_path": "m.tif",
            "potential_image_path": "p.tif",
            "output_dir": "out6",
        },
        driver,
    )
    assert result == {"n_mitochondria": 9}
    args = driver.last_args()
    assert args["morphology_image_path"] == "m.tif"
    assert args["potential_image_path"] == "p.tif"


def test_analyze_mitochondrial_morphology_missing_required_arg_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_mitochondrial_morphology_and_potential({"morphology_image_path": "m.tif"}, driver)
    assert driver.calls == []


# --- analyze_cell_morphology_and_cytoskeleton -------------------------------


def test_analyze_cell_morphology_and_cytoskeleton_valid_args_round_trip():
    driver = _driver({"n_cells": 20})
    result = analyze_cell_morphology_and_cytoskeleton(
        {"image_path": "c.tif", "output_dir": "out7", "threshold_method": "mean"}, driver
    )
    assert result == {"n_cells": 20}
    assert driver.last_args()["threshold_method"] == "mean"


def test_analyze_cell_morphology_and_cytoskeleton_invalid_method_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_cell_morphology_and_cytoskeleton({"image_path": "c.tif", "threshold_method": "x"}, driver)
    assert driver.calls == []


# --- analyze_tissue_deformation_flow ---------------------------------------


def test_analyze_tissue_deformation_flow_valid_args_round_trip():
    driver = _driver({"n_frame_pairs": 1})
    frames = [[[1, 2], [3, 4]], [[2, 3], [4, 5]]]
    result = analyze_tissue_deformation_flow(
        {"image_sequence": frames, "output_dir": "out8", "pixel_scale": 2.0}, driver
    )
    assert result == {"n_frame_pairs": 1}
    args = driver.last_args()
    assert args["image_sequence"] == frames
    assert args["pixel_scale"] == 2.0
    assert args["output_dir"] == "out8"


def test_analyze_tissue_deformation_flow_too_few_frames_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_tissue_deformation_flow({"image_sequence": [[[1, 2]]]}, driver)
    assert driver.calls == []


# --- analyze_cell_senescence_and_apoptosis ----------------------------------


def test_analyze_cell_senescence_and_apoptosis_valid_args_round_trip():
    driver = _driver({"pct_live": 80.0})
    result = analyze_cell_senescence_and_apoptosis({"fcs_file_path": "data/sample.fcs"}, driver)
    assert result == {"pct_live": 80.0}
    assert driver.last_args() == {"fcs_file_path": "data/sample.fcs"}


def test_analyze_cell_senescence_and_apoptosis_missing_arg_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_cell_senescence_and_apoptosis({}, driver)
    assert driver.calls == []


# --- perform_facs_cell_sorting ----------------------------------------------


def test_perform_facs_cell_sorting_valid_args_round_trip():
    driver = _driver({"n_sorted": 100})
    result = perform_facs_cell_sorting(
        {
            "cell_suspension_data": "cells.csv",
            "fluorescence_parameter": "GFP",
            "threshold_min": 10.0,
            "threshold_max": 500.0,
            "output_file": "sorted.csv",
        },
        driver,
    )
    assert result == {"n_sorted": 100}
    args = driver.last_args()
    assert args["fluorescence_parameter"] == "GFP"
    assert args["threshold_min"] == 10.0
    assert args["output_file"] == "sorted.csv"


def test_perform_facs_cell_sorting_empty_parameter_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        perform_facs_cell_sorting(
            {"cell_suspension_data": "cells.csv", "fluorescence_parameter": "   "}, driver
        )
    assert driver.calls == []


def test_perform_facs_cell_sorting_rejects_traversal_in_output_file():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        perform_facs_cell_sorting(
            {
                "cell_suspension_data": "cells.csv",
                "fluorescence_parameter": "GFP",
                "output_file": "../../escape.csv",
            },
            driver,
        )
    assert driver.calls == []


# --- analyze_flow_cytometry_immunophenotyping -------------------------------


def test_analyze_flow_cytometry_immunophenotyping_valid_args_round_trip():
    driver = _driver({"n_final_population": 42})
    gating_strategy = {"gate1": {"channel": "CD3", "min": 100}}
    result = analyze_flow_cytometry_immunophenotyping(
        {"fcs_file_path": "d.fcs", "gating_strategy": gating_strategy, "output_dir": "out11"},
        driver,
    )
    assert result == {"n_final_population": 42}
    assert driver.last_args()["gating_strategy"] == gating_strategy


def test_analyze_flow_cytometry_immunophenotyping_empty_gating_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_flow_cytometry_immunophenotyping(
            {"fcs_file_path": "d.fcs", "gating_strategy": {}}, driver
        )
    assert driver.calls == []


def test_analyze_flow_cytometry_immunophenotyping_gate_missing_channel_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_flow_cytometry_immunophenotyping(
            {"fcs_file_path": "d.fcs", "gating_strategy": {"gate1": {"min": 1}}}, driver
        )
    assert driver.calls == []


def test_analyze_flow_cytometry_immunophenotyping_non_square_compensation_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_flow_cytometry_immunophenotyping(
            {
                "fcs_file_path": "d.fcs",
                "gating_strategy": {"gate1": {"channel": "CD3"}},
                "compensation_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0]],
            },
            driver,
        )
    assert driver.calls == []


# --- analyze_cfse_cell_proliferation ----------------------------------------


def test_analyze_cfse_cell_proliferation_valid_args_round_trip():
    driver = _driver({"proliferation_index": 1.5})
    result = analyze_cfse_cell_proliferation(
        {"fcs_file_path": "e.fcs", "cfse_channel": "FL1-A", "lymphocyte_gate": [100, 5000]}, driver
    )
    assert result == {"proliferation_index": 1.5}
    args = driver.last_args()
    assert args["cfse_channel"] == "FL1-A"
    assert args["lymphocyte_gate"] == [100, 5000]


def test_analyze_cfse_cell_proliferation_missing_required_arg_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_cfse_cell_proliferation({"cfse_channel": "FL1-A"}, driver)
    assert driver.calls == []


# --- estimate_cell_cycle_phase_durations (Tier B) ---------------------------


def test_estimate_cell_cycle_phase_durations_valid_args_round_trip():
    driver = _driver({"T_G1_hours": 9.5})
    flow_data = {"time_points": [0, 1, 2, 4], "fraction_S": [0.05, 0.3, 0.4, 0.1]}
    initial = {"T_G1": 10.0, "T_S": 8.0, "T_G2M": 4.0}
    result = estimate_cell_cycle_phase_durations(
        {"flow_cytometry_data": flow_data, "initial_estimates": initial}, driver
    )
    assert result == {"T_G1_hours": 9.5}
    args = driver.last_args()
    assert args["flow_cytometry_data"] == flow_data
    assert args["initial_estimates"] == initial


def test_estimate_cell_cycle_phase_durations_missing_time_points_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        estimate_cell_cycle_phase_durations(
            {"flow_cytometry_data": {"fraction_S": [0.1]}, "initial_estimates": {}}, driver
        )
    assert driver.calls == []


def test_estimate_cell_cycle_phase_durations_missing_fraction_key_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        estimate_cell_cycle_phase_durations(
            {"flow_cytometry_data": {"time_points": [0, 1]}, "initial_estimates": {}}, driver
        )
    assert driver.calls == []


# --- predict_protein_disorder_regions (Tier A) ------------------------------


def test_predict_protein_disorder_regions_valid_args_round_trip():
    driver = _driver({"pct_disordered": 12.5})
    result = predict_protein_disorder_regions(
        {"protein_sequence": "meseqproteinsequence", "threshold": 0.6, "output_file": "disorder.csv"},
        driver,
    )
    assert result == {"pct_disordered": 12.5}
    args = driver.last_args()
    # Sequence is normalized to uppercase by the Pydantic validator.
    assert args["protein_sequence"] == "MESEQPROTEINSEQUENCE"
    assert args["threshold"] == 0.6
    assert args["output_file"] == "disorder.csv"


def test_predict_protein_disorder_regions_invalid_residue_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        predict_protein_disorder_regions({"protein_sequence": "MSE1QRTY"}, driver)
    assert driver.calls == []


def test_predict_protein_disorder_regions_threshold_out_of_range_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        predict_protein_disorder_regions({"protein_sequence": "MSEQ", "threshold": 1.5}, driver)
    assert driver.calls == []


def test_predict_protein_disorder_regions_empty_sequence_raises_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        predict_protein_disorder_regions({"protein_sequence": "   "}, driver)
    assert driver.calls == []


# --- register_cell_imaging_tools --------------------------------------------


EXPECTED_TOOL_NAMES = {
    "analyze_cell_migration_metrics",
    "analyze_calcium_imaging_data",
    "analyze_myofiber_morphology",
    "quantify_cell_cycle_phases_from_microscopy",
    "quantify_and_cluster_cell_motility",
    "analyze_mitochondrial_morphology_and_potential",
    "analyze_cell_morphology_and_cytoskeleton",
    "analyze_tissue_deformation_flow",
    "analyze_cell_senescence_and_apoptosis",
    "perform_facs_cell_sorting",
    "analyze_flow_cytometry_immunophenotyping",
    "analyze_cfse_cell_proliferation",
    "estimate_cell_cycle_phase_durations",
    "predict_protein_disorder_regions",
}


def test_register_cell_imaging_tools_registers_all_fourteen_tools():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    registered = register_cell_imaging_tools(registry, driver)

    assert set(registered) == EXPECTED_TOOL_NAMES
    assert EXPECTED_TOOL_NAMES.issubset(registry.registry.keys())


@pytest.mark.asyncio
async def test_register_cell_imaging_tools_registered_handler_is_routable():
    registry = MCPServerRegistry()
    driver = _driver({"n_events": 500})

    register_cell_imaging_tools(registry, driver)

    out = await registry.route("analyze_cell_senescence_and_apoptosis", {"fcs_file_path": "s.fcs"})
    assert "500" in out
    assert driver.last_args() == {"fcs_file_path": "s.fcs"}
