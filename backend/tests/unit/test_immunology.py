"""Unit tests for `infrastructure/tools/immunology.py` (Fase 5, "Categoria:
Imunologia"). Per `_sandbox_tool_base.py`'s "TESTING REALITY" docstring
section, these tests verify the WIRING and VALIDATION layer only (argument
validation, `args` JSON round-tripping via `FakeSandboxDriver`, tool
registration) -- the sandboxed `script_body` strings import scipy/scikit-image/
trackpy/flowio, which only exist in the sandbox toolkit's own conda env, never
in this repo's pytest venv."""
import json

import pytest
from pydantic import ValidationError

from src.domain.services.path_guard import PathTraversalError
from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver
from src.infrastructure.tools.immunology import (
    analyze_cns_lesion_histology,
    analyze_cytokine_production_in_cd4_tcells,
    analyze_ebv_antibody_titers,
    analyze_immunohistochemistry_image,
    isolate_purify_immune_cells,
    register_immunology_tools,
    track_immune_cells_under_flow,
)


@pytest.fixture
def driver(tmp_path):
    return FakeSandboxDriver(workspace_root=str(tmp_path / "workspace_fake_tools"))


# --- isolate_purify_immune_cells (Tier A) --------------------------------


def test_isolate_purify_immune_cells_valid_args_round_trip(driver):
    driver.stdout = json.dumps({"protocol_steps": ["1. Harvest spleen..."]})

    result = isolate_purify_immune_cells(
        {
            "tissue_type": "spleen",
            "target_cell_type": "CD4 T cell",
            "enzyme_type": "collagenase",
            "digestion_time_min": 30,
        },
        driver,
    )

    assert driver.last_args() == {
        "tissue_type": "spleen",
        "target_cell_type": "CD4 T cell",
        "enzyme_type": "collagenase",
        "macs_antibody": None,
        "digestion_time_min": 30,
    }
    assert result == {"protocol_steps": ["1. Harvest spleen..."]}


def test_isolate_purify_immune_cells_applies_defaults(driver):
    driver.stdout = json.dumps({"ok": True})

    isolate_purify_immune_cells({"tissue_type": "lymph node", "target_cell_type": "B cell"}, driver)

    args = driver.last_args()
    assert args["enzyme_type"] == "collagenase"
    assert args["digestion_time_min"] == 45
    assert args["macs_antibody"] is None


def test_isolate_purify_immune_cells_missing_required_field_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        isolate_purify_immune_cells({"target_cell_type": "B cell"}, driver)

    assert driver.calls == []


def test_isolate_purify_immune_cells_rejects_nonpositive_digestion_time(driver):
    with pytest.raises(ValidationError):
        isolate_purify_immune_cells(
            {"tissue_type": "spleen", "target_cell_type": "T cell", "digestion_time_min": 0},
            driver,
        )

    assert driver.calls == []


# --- track_immune_cells_under_flow (Tier C) ------------------------------


def test_track_immune_cells_under_flow_valid_args_round_trip(driver):
    driver.stdout = json.dumps({"cells": [], "summary": {"n_cells_tracked": 0}})

    result = track_immune_cells_under_flow(
        {
            "image_sequence_path": "sequences/flow_run_1",
            "output_dir": "results/flow",
            "pixel_size_um": 0.65,
            "time_interval_sec": 2.0,
            "flow_direction": "left",
        },
        driver,
    )

    assert driver.last_args() == {
        "image_sequence_path": "sequences/flow_run_1",
        "output_dir": "results/flow",
        "pixel_size_um": 0.65,
        "time_interval_sec": 2.0,
        "flow_direction": "left",
    }
    assert result == {"cells": [], "summary": {"n_cells_tracked": 0}}


def test_track_immune_cells_under_flow_missing_required_field_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        track_immune_cells_under_flow({}, driver)

    assert driver.calls == []


def test_track_immune_cells_under_flow_invalid_direction_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        track_immune_cells_under_flow(
            {"image_sequence_path": "seq", "flow_direction": "sideways"}, driver
        )

    assert driver.calls == []


def test_track_immune_cells_under_flow_rejects_path_traversal(driver):
    with pytest.raises(PathTraversalError):
        track_immune_cells_under_flow({"image_sequence_path": "../../etc/passwd"}, driver)

    assert driver.calls == []


def test_track_immune_cells_under_flow_rejects_absolute_output_dir(driver):
    with pytest.raises(PathTraversalError):
        track_immune_cells_under_flow(
            {"image_sequence_path": "seq", "output_dir": "C:\\Windows\\System32"}, driver
        )

    assert driver.calls == []


# --- analyze_cytokine_production_in_cd4_tcells (Tier C) ------------------


def test_analyze_cytokine_production_valid_args_round_trip(driver):
    driver.stdout = json.dumps({"results_by_condition": {}})

    result = analyze_cytokine_production_in_cd4_tcells(
        {
            "fcs_files_dict": {
                "unstimulated": "fcs/unstim.fcs",
                "PMA_ionomycin": "fcs/pma.fcs",
            },
            "output_dir": "results/cytokines",
        },
        driver,
    )

    assert driver.last_args() == {
        "fcs_files_dict": {
            "unstimulated": "fcs/unstim.fcs",
            "PMA_ionomycin": "fcs/pma.fcs",
        },
        "output_dir": "results/cytokines",
    }
    assert result == {"results_by_condition": {}}


def test_analyze_cytokine_production_empty_dict_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        analyze_cytokine_production_in_cd4_tcells({"fcs_files_dict": {}}, driver)

    assert driver.calls == []


def test_analyze_cytokine_production_missing_required_field_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        analyze_cytokine_production_in_cd4_tcells({}, driver)

    assert driver.calls == []


def test_analyze_cytokine_production_rejects_path_traversal_in_dict_value(driver):
    with pytest.raises(PathTraversalError):
        analyze_cytokine_production_in_cd4_tcells(
            {"fcs_files_dict": {"unstim": "../../../etc/passwd"}}, driver
        )

    assert driver.calls == []


# --- analyze_ebv_antibody_titers (Tier B) --------------------------------


_STANDARD_CURVE = {
    "concentrations": [0, 10, 100, 1000, 10000],
    "od_values": [0.05, 0.2, 0.9, 2.1, 2.8],
}


def test_analyze_ebv_antibody_titers_valid_args_round_trip(driver):
    driver.stdout = json.dumps({"fit_params": {"A": 1}, "titers": {}})

    result = analyze_ebv_antibody_titers(
        {
            "raw_od_data": {"sample_1": 1.1, "sample_2": 0.4},
            "standard_curve_data": _STANDARD_CURVE,
            "sample_metadata": {"sample_1": {"cohort": "A"}},
            "output_dir": "results/ebv",
        },
        driver,
    )

    assert driver.last_args() == {
        "raw_od_data": {"sample_1": 1.1, "sample_2": 0.4},
        "standard_curve_data": _STANDARD_CURVE,
        "sample_metadata": {"sample_1": {"cohort": "A"}},
        "output_dir": "results/ebv",
    }
    assert result == {"fit_params": {"A": 1}, "titers": {}}


def test_analyze_ebv_antibody_titers_missing_raw_od_data_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        analyze_ebv_antibody_titers({"standard_curve_data": _STANDARD_CURVE}, driver)

    assert driver.calls == []


def test_analyze_ebv_antibody_titers_malformed_standard_curve_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        analyze_ebv_antibody_titers(
            {
                "raw_od_data": {"sample_1": 1.1},
                "standard_curve_data": {"concentrations": [0, 10], "od_values": [0.1, 0.2]},
            },
            driver,
        )

    assert driver.calls == []


def test_analyze_ebv_antibody_titers_mismatched_curve_lengths_raise_before_sandbox(driver):
    with pytest.raises(ValidationError):
        analyze_ebv_antibody_titers(
            {
                "raw_od_data": {"sample_1": 1.1},
                "standard_curve_data": {
                    "concentrations": [0, 10, 100, 1000],
                    "od_values": [0.1, 0.2, 0.3],
                },
            },
            driver,
        )

    assert driver.calls == []


# --- analyze_cns_lesion_histology (Tier C) -------------------------------


def test_analyze_cns_lesion_histology_valid_args_round_trip(driver):
    driver.stdout = json.dumps({"immune_infiltrate_area_fraction": 0.12})

    result = analyze_cns_lesion_histology(
        {"image_path": "images/lesion_01.tif", "stain_type": "LFB"}, driver
    )

    assert driver.last_args() == {
        "image_path": "images/lesion_01.tif",
        "output_dir": "output",
        "stain_type": "LFB",
    }
    assert result == {"immune_infiltrate_area_fraction": 0.12}


def test_analyze_cns_lesion_histology_missing_image_path_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        analyze_cns_lesion_histology({}, driver)

    assert driver.calls == []


def test_analyze_cns_lesion_histology_rejects_path_traversal(driver):
    with pytest.raises(PathTraversalError):
        analyze_cns_lesion_histology({"image_path": "../secrets.tif"}, driver)

    assert driver.calls == []


# --- analyze_immunohistochemistry_image (Tier C) -------------------------


def test_analyze_immunohistochemistry_image_valid_args_round_trip(driver):
    driver.stdout = json.dumps({"h_score": 150.0})

    result = analyze_immunohistochemistry_image(
        {"image_path": "images/ihc_01.tif", "protein_name": "CD3"}, driver
    )

    assert driver.last_args() == {
        "image_path": "images/ihc_01.tif",
        "protein_name": "CD3",
        "output_dir": "ihc_results",
    }
    assert result == {"h_score": 150.0}


def test_analyze_immunohistochemistry_image_missing_image_path_raises_before_sandbox(driver):
    with pytest.raises(ValidationError):
        analyze_immunohistochemistry_image({"protein_name": "CD3"}, driver)

    assert driver.calls == []


def test_analyze_immunohistochemistry_image_rejects_absolute_image_path(driver):
    with pytest.raises(PathTraversalError):
        analyze_immunohistochemistry_image({"image_path": "/etc/passwd"}, driver)

    assert driver.calls == []


# --- register_immunology_tools -------------------------------------------


def test_register_immunology_tools_registers_all_six_tool_names():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    registered = register_immunology_tools(registry, driver)

    assert set(registered) == {
        "isolate_purify_immune_cells",
        "track_immune_cells_under_flow",
        "analyze_cytokine_production_in_cd4_tcells",
        "analyze_ebv_antibody_titers",
        "analyze_cns_lesion_histology",
        "analyze_immunohistochemistry_image",
    }
    for tool_name in registered:
        assert tool_name in registry.registry
        assert callable(registry.registry[tool_name])


def test_register_immunology_tools_bound_handler_uses_the_given_driver():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"ok": True})

    register_immunology_tools(registry, driver)
    handler = registry.registry["isolate_purify_immune_cells"]

    result = handler({"tissue_type": "spleen", "target_cell_type": "T cell"})

    assert result == {"ok": True}
    assert driver.calls  # the FakeSandboxDriver passed to register_* was actually used
