"""Unit tests for `infrastructure/tools/biophysics_assays.py` (Fase 5).

Per `_sandbox_tool_base.py`'s module docstring, `script_body` strings here
import packages (scipy, ViennaRNA, Biopython, ...) that only exist in the
sandbox toolkit's own conda env, never in this repo's own pytest venv. These
tests therefore verify the WIRING and VALIDATION layer only, using
`FakeSandboxDriver`: Pydantic argument validation (valid args round-trip,
missing/malformed required args raise before the sandbox is ever touched),
path-traversal guarding, and registration -- never real numeric/scientific
correctness of a `script_body`, which cannot be executed here by design.
"""
import json

import pytest
from pydantic import ValidationError

from src.domain.services.path_guard import PathTraversalError
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver
from src.infrastructure.tools.biophysics_assays import (
    _TOOL_HANDLERS,
    analyze_atp_luminescence_assay,
    analyze_bacterial_growth_curve,
    analyze_bacterial_growth_rate,
    analyze_circular_dichroism_spectra,
    analyze_enzyme_kinetics_assay,
    analyze_itc_binding_thermodynamics,
    analyze_protease_kinetics,
    analyze_protein_conservation,
    analyze_rna_secondary_structure_features,
    register_biophysics_assays_tools,
)
from src.infrastructure.mcp.server_registry import MCPServerRegistry


def _driver_with(result: dict) -> FakeSandboxDriver:
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps(result)
    return driver


# ---------------------------------------------------------------------------
# analyze_circular_dichroism_spectra
# ---------------------------------------------------------------------------


def test_analyze_cd_spectra_valid_args_round_trip_and_result():
    driver = _driver_with({"sample_name": "mAb1", "secondary_structure": {"estimated_helix_fraction": 0.4}})

    result = analyze_circular_dichroism_spectra(
        {
            "sample_name": "mAb1",
            "sample_type": "protein",
            "wavelength_data": [195.0, 208.0, 222.0],
            "cd_signal_data": [-1000.0, -12000.0, -11000.0],
            "output_dir": "cd_out",
        },
        driver,
    )

    assert result == {"sample_name": "mAb1", "secondary_structure": {"estimated_helix_fraction": 0.4}}
    args = driver.last_args()
    assert args["sample_name"] == "mAb1"
    assert args["wavelength_data"] == [195.0, 208.0, 222.0]
    assert args["cd_signal_data"] == [-1000.0, -12000.0, -11000.0]
    assert args["output_dir"] == "cd_out"
    assert args["temperature_data"] is None


def test_analyze_cd_spectra_missing_required_field_raises_before_sandbox():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError):
        analyze_circular_dichroism_spectra(
            {"sample_name": "mAb1", "sample_type": "protein", "wavelength_data": [195.0, 208.0]},
            driver,
        )
    assert driver.calls == []


def test_analyze_cd_spectra_mismatched_lengths_raise_validation_error():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="same length"):
        analyze_circular_dichroism_spectra(
            {
                "sample_name": "mAb1",
                "sample_type": "protein",
                "wavelength_data": [195.0, 208.0, 222.0],
                "cd_signal_data": [-1000.0, -12000.0],
            },
            driver,
        )
    assert driver.calls == []


def test_analyze_cd_spectra_path_traversal_output_dir_rejected():
    driver = FakeSandboxDriver()

    with pytest.raises(PathTraversalError):
        analyze_circular_dichroism_spectra(
            {
                "sample_name": "mAb1",
                "sample_type": "protein",
                "wavelength_data": [195.0, 208.0],
                "cd_signal_data": [-1000.0, -12000.0],
                "output_dir": "../../etc",
            },
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_rna_secondary_structure_features
# ---------------------------------------------------------------------------


def test_analyze_rna_secondary_structure_valid_args_round_trip():
    driver = _driver_with({"num_base_pairs": 3})

    result = analyze_rna_secondary_structure_features(
        {"dot_bracket_structure": "((...))", "sequence": "GCAAAGC"},
        driver,
    )

    assert result == {"num_base_pairs": 3}
    args = driver.last_args()
    assert args["dot_bracket_structure"] == "((...))"
    assert args["sequence"] == "GCAAAGC"


def test_analyze_rna_secondary_structure_missing_required_field_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError):
        analyze_rna_secondary_structure_features({}, driver)
    assert driver.calls == []


def test_analyze_rna_secondary_structure_invalid_chars_raise():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="unsupported characters"):
        analyze_rna_secondary_structure_features({"dot_bracket_structure": "((XYZ))"}, driver)
    assert driver.calls == []


def test_analyze_rna_secondary_structure_sequence_length_mismatch_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="sequence length"):
        analyze_rna_secondary_structure_features(
            {"dot_bracket_structure": "((...))", "sequence": "GC"}, driver
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_protease_kinetics
# ---------------------------------------------------------------------------


def test_analyze_protease_kinetics_valid_args_round_trip():
    driver = _driver_with({"vmax": 10.0, "km": 5.0})

    result = analyze_protease_kinetics(
        {
            "time_points": [0.0, 1.0, 2.0],
            "fluorescence_data": [[0.0, 1.0, 2.0], [0.0, 2.0, 4.0]],
            "substrate_concentrations": [1.0, 10.0],
            "enzyme_concentration": 0.5,
            "output_prefix": "run1",
            "output_dir": "kinetics_out",
        },
        driver,
    )

    assert result == {"vmax": 10.0, "km": 5.0}
    args = driver.last_args()
    assert args["fluorescence_data"] == [[0.0, 1.0, 2.0], [0.0, 2.0, 4.0]]
    assert args["enzyme_concentration"] == 0.5
    assert args["output_prefix"] == "run1"
    assert args["output_dir"] == "kinetics_out"


def test_analyze_protease_kinetics_missing_enzyme_concentration_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError):
        analyze_protease_kinetics(
            {
                "time_points": [0.0, 1.0, 2.0],
                "fluorescence_data": [[0.0, 1.0, 2.0]],
                "substrate_concentrations": [1.0],
            },
            driver,
        )
    assert driver.calls == []


def test_analyze_protease_kinetics_shape_mismatch_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="one row per"):
        analyze_protease_kinetics(
            {
                "time_points": [0.0, 1.0, 2.0],
                "fluorescence_data": [[0.0, 1.0, 2.0]],
                "substrate_concentrations": [1.0, 10.0],
                "enzyme_concentration": 0.5,
            },
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_enzyme_kinetics_assay
# ---------------------------------------------------------------------------


def test_analyze_enzyme_kinetics_assay_valid_args_round_trip():
    driver = _driver_with({"modulators": {"compound_x": {"ec50_or_ic50": 3.2}}})

    result = analyze_enzyme_kinetics_assay(
        {
            "enzyme_name": "trypsin",
            "substrate_concentrations": [1.0, 5.0, 10.0],
            "enzyme_concentration": 0.1,
            "modulators": {
                "compound_x": {
                    "concentrations": [0.0, 1.0, 10.0, 100.0],
                    "velocities": [10.0, 8.0, 4.0, 1.0],
                    "mode": "inhibitor",
                }
            },
            "output_dir": "enzyme_out",
        },
        driver,
    )

    assert result == {"modulators": {"compound_x": {"ec50_or_ic50": 3.2}}}
    args = driver.last_args()
    assert args["enzyme_name"] == "trypsin"
    assert args["modulators"]["compound_x"]["concentrations"] == [0.0, 1.0, 10.0, 100.0]
    assert args["modulators"]["compound_x"]["velocities"] == [10.0, 8.0, 4.0, 1.0]
    assert args["modulators"]["compound_x"]["mode"] == "inhibitor"
    assert args["output_dir"] == "enzyme_out"


def test_analyze_enzyme_kinetics_assay_missing_modulators_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="modulators must include"):
        analyze_enzyme_kinetics_assay(
            {
                "enzyme_name": "trypsin",
                "substrate_concentrations": [1.0, 5.0],
                "enzyme_concentration": 0.1,
            },
            driver,
        )
    assert driver.calls == []


def test_analyze_enzyme_kinetics_assay_invalid_mode_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="mode must be"):
        analyze_enzyme_kinetics_assay(
            {
                "enzyme_name": "trypsin",
                "substrate_concentrations": [1.0],
                "enzyme_concentration": 0.1,
                "modulators": {
                    "compound_x": {
                        "concentrations": [0.0, 1.0],
                        "velocities": [10.0, 8.0],
                        "mode": "not_a_real_mode",
                    }
                },
            },
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_itc_binding_thermodynamics
# ---------------------------------------------------------------------------


def test_analyze_itc_binding_thermodynamics_valid_args_round_trip_with_inline_data():
    driver = _driver_with({"stoichiometry_n": 1.0, "association_constant_Ka_per_M": 1e6})

    result = analyze_itc_binding_thermodynamics(
        {
            "itc_data": [[0.5, -5.0], [1.0, -6.0], [1.5, -4.0], [2.0, -2.0], [2.5, -1.0]],
            "temperature": 298.15,
            "protein_concentration": 1e-5,
        },
        driver,
    )

    assert result == {"stoichiometry_n": 1.0, "association_constant_Ka_per_M": 1e6}
    args = driver.last_args()
    assert args["itc_data"] == [[0.5, -5.0], [1.0, -6.0], [1.5, -4.0], [2.0, -2.0], [2.5, -1.0]]
    assert args["itc_data_path"] is None
    assert args["protein_concentration"] == 1e-5


def test_analyze_itc_binding_thermodynamics_missing_data_source_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="itc_data_path or itc_data"):
        analyze_itc_binding_thermodynamics({"temperature": 298.15}, driver)
    assert driver.calls == []


def test_analyze_itc_binding_thermodynamics_path_traversal_rejected():
    driver = FakeSandboxDriver()

    with pytest.raises(PathTraversalError):
        analyze_itc_binding_thermodynamics({"itc_data_path": "/etc/passwd"}, driver)
    assert driver.calls == []


def test_analyze_itc_binding_thermodynamics_path_round_trips():
    driver = _driver_with({"ok": True})

    analyze_itc_binding_thermodynamics({"itc_data_path": "data/itc_run1.csv"}, driver)

    assert driver.last_args()["itc_data_path"] == "data/itc_run1.csv"
    assert driver.last_args()["itc_data"] is None


# ---------------------------------------------------------------------------
# analyze_protein_conservation
# ---------------------------------------------------------------------------


def test_analyze_protein_conservation_valid_args_round_trip():
    driver = _driver_with({"consensus_sequence": "MKV"})

    result = analyze_protein_conservation(
        {"protein_sequences": ["MKVLA", "MKVLS", "MKILA"], "output_dir": "conservation_out"},
        driver,
    )

    assert result == {"consensus_sequence": "MKV"}
    args = driver.last_args()
    assert args["protein_sequences"] == ["MKVLA", "MKVLS", "MKILA"]
    assert args["output_dir"] == "conservation_out"


def test_analyze_protein_conservation_requires_at_least_two_sequences():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError):
        analyze_protein_conservation({"protein_sequences": ["MKVLA"]}, driver)
    assert driver.calls == []


def test_analyze_protein_conservation_empty_sequence_rejected():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="empty strings"):
        analyze_protein_conservation({"protein_sequences": ["MKVLA", "  "]}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_atp_luminescence_assay
# ---------------------------------------------------------------------------


def test_analyze_atp_luminescence_assay_valid_args_round_trip_inline_normalization():
    driver = _driver_with({"standard_curve_slope": 1.2})

    result = analyze_atp_luminescence_assay(
        {
            "data_file": "atp/data.csv",
            "standard_curve_file": "atp/standard.csv",
            "normalization_method": "protein_amount",
            "normalization_data": {"sample_1": 2.0, "sample_2": 3.0},
        },
        driver,
    )

    assert result == {"standard_curve_slope": 1.2}
    args = driver.last_args()
    assert args["data_file"] == "atp/data.csv"
    assert args["standard_curve_file"] == "atp/standard.csv"
    assert args["normalization_data_inline"] == {"sample_1": 2.0, "sample_2": 3.0}
    assert args["normalization_data_path"] is None


def test_analyze_atp_luminescence_assay_normalization_data_as_path_round_trips():
    driver = _driver_with({"ok": True})

    analyze_atp_luminescence_assay(
        {
            "data_file": "atp/data.csv",
            "standard_curve_file": "atp/standard.csv",
            "normalization_data": "atp/cell_counts.csv",
        },
        driver,
    )

    args = driver.last_args()
    assert args["normalization_data_path"] == "atp/cell_counts.csv"
    assert args["normalization_data_inline"] is None


def test_analyze_atp_luminescence_assay_missing_required_path_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError):
        analyze_atp_luminescence_assay({"standard_curve_file": "atp/standard.csv"}, driver)
    assert driver.calls == []


def test_analyze_atp_luminescence_assay_path_traversal_rejected():
    driver = FakeSandboxDriver()

    with pytest.raises(PathTraversalError):
        analyze_atp_luminescence_assay(
            {"data_file": "../../secrets.csv", "standard_curve_file": "atp/standard.csv"}, driver
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_bacterial_growth_curve / analyze_bacterial_growth_rate
# ---------------------------------------------------------------------------


def test_analyze_bacterial_growth_curve_valid_args_round_trip():
    driver = _driver_with({"max_growth_rate_per_time_unit": 0.5})

    result = analyze_bacterial_growth_curve(
        {
            "time_points": [0.0, 1.0, 2.0, 3.0],
            "od_values": [0.1, 0.2, 0.4, 0.8],
            "strain_name": "E. coli K-12",
            "output_dir": "growth_out",
        },
        driver,
    )

    assert result == {"max_growth_rate_per_time_unit": 0.5}
    args = driver.last_args()
    assert args["time_points"] == [0.0, 1.0, 2.0, 3.0]
    assert args["od_values"] == [0.1, 0.2, 0.4, 0.8]
    assert args["strain_name"] == "E. coli K-12"
    assert args["output_dir"] == "growth_out"


def test_analyze_bacterial_growth_curve_missing_strain_name_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError):
        analyze_bacterial_growth_curve(
            {"time_points": [0.0, 1.0, 2.0], "od_values": [0.1, 0.2, 0.4]}, driver
        )
    assert driver.calls == []


def test_analyze_bacterial_growth_curve_length_mismatch_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError, match="same length"):
        analyze_bacterial_growth_curve(
            {
                "time_points": [0.0, 1.0, 2.0, 3.0],
                "od_values": [0.1, 0.2, 0.4],
                "strain_name": "E. coli",
            },
            driver,
        )
    assert driver.calls == []


def test_analyze_bacterial_growth_rate_valid_args_round_trip_maps_od_measurements():
    driver = _driver_with({"doubling_time": 1.4})

    result = analyze_bacterial_growth_rate(
        {
            "time_points": [0.0, 1.0, 2.0, 3.0],
            "od_measurements": [0.1, 0.15, 0.3, 0.6],
        },
        driver,
    )

    assert result == {"doubling_time": 1.4}
    args = driver.last_args()
    # Handler maps the tool's own `od_measurements` param onto the shared
    # script body's `od_values` key.
    assert args["od_values"] == [0.1, 0.15, 0.3, 0.6]
    assert args["strain_name"] == "Unknown strain"
    # `ensure_safe_relative_path` normalizes "./" down to "."
    assert args["output_dir"] == "."


def test_analyze_bacterial_growth_rate_missing_required_field_raises():
    driver = FakeSandboxDriver()

    with pytest.raises(ValidationError):
        analyze_bacterial_growth_rate({"time_points": [0.0, 1.0, 2.0]}, driver)
    assert driver.calls == []


def test_analyze_bacterial_growth_curve_and_rate_share_script_body():
    import re

    driver_a = _driver_with({"ok": True})
    driver_b = _driver_with({"ok": True})

    analyze_bacterial_growth_curve(
        {"time_points": [0.0, 1.0, 2.0], "od_values": [0.1, 0.2, 0.4], "strain_name": "X"}, driver_a
    )
    analyze_bacterial_growth_rate(
        {"time_points": [0.0, 1.0, 2.0], "od_measurements": [0.1, 0.2, 0.4]}, driver_b
    )

    # Only the `run_in_sandbox`-generated preamble (which embeds a random
    # per-call args filename) differs -- normalize that out before comparing,
    # to assert the actual `_BACTERIAL_GROWTH_SCRIPT_BODY` text is identical.
    def normalize(text: str) -> str:
        return re.sub(r"_tool_args_[0-9a-f]{12}\.json", "_tool_args_X.json", text)

    script_a = normalize(driver_a.calls[-1][0])
    script_b = normalize(driver_b.calls[-1][0])
    assert script_a == script_b


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_EXPECTED_TOOL_NAMES = {
    "analyze_circular_dichroism_spectra",
    "analyze_rna_secondary_structure_features",
    "analyze_protease_kinetics",
    "analyze_enzyme_kinetics_assay",
    "analyze_itc_binding_thermodynamics",
    "analyze_protein_conservation",
    "analyze_atp_luminescence_assay",
    "analyze_bacterial_growth_curve",
    "analyze_bacterial_growth_rate",
}


def test_tool_handlers_cover_every_catalog_tool():
    assert set(_TOOL_HANDLERS.keys()) == _EXPECTED_TOOL_NAMES


def test_register_biophysics_assays_tools_registers_every_tool():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    registered = register_biophysics_assays_tools(registry, driver)

    assert set(registered) == _EXPECTED_TOOL_NAMES
    assert set(registered).issubset(registry.registry.keys())


def test_registered_handler_is_bound_to_driver_and_callable_with_arguments_only():
    registry = MCPServerRegistry()
    driver = _driver_with({"num_base_pairs": 1})

    register_biophysics_assays_tools(registry, driver)
    handler = registry.registry["analyze_rna_secondary_structure_features"]

    # `MCPServerRegistry.route` calls `handler(arguments)` with a single
    # positional dict -- the registered handler must already be bound to
    # `driver` (via functools.partial), not require it as a second arg here.
    result = handler({"dot_bracket_structure": "(...)"})

    assert result == {"num_base_pairs": 1}
    assert driver.last_args()["dot_bracket_structure"] == "(...)"
