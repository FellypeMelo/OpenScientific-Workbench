"""Unit tests for the Physiology / cardio / neuro / imaging action tools
(Fase 5, "Categoria: Fisiologia / cardio / neuro / imaging").

Per `_sandbox_tool_base.py`'s documented testing boundary, these tests
exercise argument validation + sandbox wiring via `FakeSandboxDriver`, never
the real scientific `script_body` logic (which needs scikit-image/scipy/
nibabel/opencv/sklearn from the sandbox toolkit's own conda env, not this
repo's pytest venv)."""
import json

import pytest
from pydantic import ValidationError

from src.domain.services.path_guard import PathTraversalError
from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver
from src.infrastructure.tools.physiology_imaging import (
    analyze_abr_waveform_p1_metrics,
    analyze_aortic_diameter_and_geometry,
    analyze_bone_microct_morphometry,
    analyze_ciliary_beat_frequency,
    analyze_endolysosomal_calcium_dynamics,
    analyze_fatty_acid_composition_by_gc,
    analyze_hemodynamic_data,
    analyze_intracellular_calcium_with_rhod2,
    analyze_protein_colocalization,
    analyze_thrombus_histology,
    calculate_brain_adc_map,
    decode_behavior_from_neural_trajectories,
    perform_cosinor_analysis,
    quantify_amyloid_beta_plaques,
    quantify_corneal_nerve_fibers,
    reconstruct_3d_face_from_mri,
    register_physiology_imaging_tools,
    segment_and_quantify_cells_in_multiplexed_images,
    simulate_thyroid_hormone_pharmacokinetics,
)

ALL_TOOL_NAMES = {
    "analyze_aortic_diameter_and_geometry",
    "analyze_thrombus_histology",
    "analyze_intracellular_calcium_with_rhod2",
    "quantify_corneal_nerve_fibers",
    "segment_and_quantify_cells_in_multiplexed_images",
    "analyze_bone_microct_morphometry",
    "reconstruct_3d_face_from_mri",
    "analyze_abr_waveform_p1_metrics",
    "analyze_ciliary_beat_frequency",
    "analyze_protein_colocalization",
    "perform_cosinor_analysis",
    "calculate_brain_adc_map",
    "analyze_endolysosomal_calcium_dynamics",
    "analyze_fatty_acid_composition_by_gc",
    "analyze_hemodynamic_data",
    "simulate_thyroid_hormone_pharmacokinetics",
    "quantify_amyloid_beta_plaques",
    "decode_behavior_from_neural_trajectories",
}


# --- analyze_aortic_diameter_and_geometry -----------------------------------


def test_analyze_aortic_diameter_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"equivalent_diameter": 24.5, "units": "px"})

    result = analyze_aortic_diameter_and_geometry(
        {"image_path": "scans/aorta.png", "output_dir": "out"}, driver
    )

    assert result == {"equivalent_diameter": 24.5, "units": "px"}
    assert driver.last_args() == {"image_path": "scans/aorta.png", "output_dir": "out"}


def test_analyze_aortic_diameter_missing_image_path_raises_before_sandbox_call():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_aortic_diameter_and_geometry({}, driver)
    assert driver.calls == []


def test_analyze_aortic_diameter_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_aortic_diameter_and_geometry({"image_path": "../../etc/passwd"}, driver)
    assert driver.calls == []


# --- analyze_thrombus_histology ----------------------------------------------


def test_analyze_thrombus_histology_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"rbc_rich_fraction": 0.4})

    result = analyze_thrombus_histology(
        {"image_path": "histo/thrombus.png", "output_dir": "out"}, driver
    )

    assert result == {"rbc_rich_fraction": 0.4}
    assert driver.last_args() == {"image_path": "histo/thrombus.png", "output_dir": "out"}


def test_analyze_thrombus_histology_missing_image_path_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_thrombus_histology({"output_dir": "out"}, driver)
    assert driver.calls == []


def test_analyze_thrombus_histology_path_traversal_in_output_dir_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_thrombus_histology(
            {"image_path": "histo/thrombus.png", "output_dir": "/etc"}, driver
        )
    assert driver.calls == []


# --- analyze_intracellular_calcium_with_rhod2 -------------------------------


def test_analyze_rhod2_calcium_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"f_over_f0_ratio": 1.8})

    result = analyze_intracellular_calcium_with_rhod2(
        {
            "background_image_path": "img/bg.tif",
            "control_image_path": "img/control.tif",
            "sample_image_path": "img/sample.tif",
            "output_dir": "out",
        },
        driver,
    )

    assert result == {"f_over_f0_ratio": 1.8}
    assert driver.last_args() == {
        "background_image_path": "img/bg.tif",
        "control_image_path": "img/control.tif",
        "sample_image_path": "img/sample.tif",
        "output_dir": "out",
    }


def test_analyze_rhod2_calcium_missing_required_field_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_intracellular_calcium_with_rhod2(
            {"background_image_path": "img/bg.tif", "control_image_path": "img/control.tif"},
            driver,
        )
    assert driver.calls == []


def test_analyze_rhod2_calcium_path_traversal_in_sample_image_path_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_intracellular_calcium_with_rhod2(
            {
                "background_image_path": "img/bg.tif",
                "control_image_path": "img/control.tif",
                "sample_image_path": "C:\\Windows\\system.ini",
            },
            driver,
        )
    assert driver.calls == []


# --- quantify_corneal_nerve_fibers ------------------------------------------


def test_quantify_corneal_nerve_fibers_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"fiber_length_px": 1200, "branch_point_count": 5})

    result = quantify_corneal_nerve_fibers(
        {
            "image_path": "cornea/if.png",
            "marker_type": "beta-III-tubulin",
            "output_dir": "out",
            "threshold_method": "otsu",
        },
        driver,
    )

    assert result == {"fiber_length_px": 1200, "branch_point_count": 5}
    args = driver.last_args()
    assert args["marker_type"] == "beta-III-tubulin"
    assert args["threshold_method"] == "otsu"


def test_quantify_corneal_nerve_fibers_missing_marker_type_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        quantify_corneal_nerve_fibers({"image_path": "cornea/if.png"}, driver)
    assert driver.calls == []


def test_quantify_corneal_nerve_fibers_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        quantify_corneal_nerve_fibers(
            {"image_path": "../secrets.png", "marker_type": "PGP9.5"}, driver
        )
    assert driver.calls == []


# --- segment_and_quantify_cells_in_multiplexed_images -----------------------


def test_segment_multiplexed_cells_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"cell_count": 340})

    result = segment_and_quantify_cells_in_multiplexed_images(
        {
            "image_path": "multiplex/panel.tif",
            "markers_list": ["DAPI", "CD3", "CD8"],
            "nuclear_channel_index": 0,
            "output_dir": "out",
        },
        driver,
    )

    assert result == {"cell_count": 340}
    args = driver.last_args()
    assert args["markers_list"] == ["DAPI", "CD3", "CD8"]
    assert args["nuclear_channel_index"] == 0


def test_segment_multiplexed_cells_missing_markers_list_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        segment_and_quantify_cells_in_multiplexed_images(
            {"image_path": "multiplex/panel.tif"}, driver
        )
    assert driver.calls == []


def test_segment_multiplexed_cells_empty_markers_list_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        segment_and_quantify_cells_in_multiplexed_images(
            {"image_path": "multiplex/panel.tif", "markers_list": []}, driver
        )
    assert driver.calls == []


def test_segment_multiplexed_cells_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        segment_and_quantify_cells_in_multiplexed_images(
            {"image_path": "../../panel.tif", "markers_list": ["DAPI"]}, driver
        )
    assert driver.calls == []


# --- analyze_bone_microct_morphometry ---------------------------------------


def test_analyze_bone_microct_morphometry_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"bv_tv_fraction": 0.23})

    result = analyze_bone_microct_morphometry(
        {"input_file_path": "microct/femur.nii.gz", "output_dir": "res", "threshold_value": 220.0},
        driver,
    )

    assert result == {"bv_tv_fraction": 0.23}
    assert driver.last_args() == {
        "input_file_path": "microct/femur.nii.gz",
        "output_dir": "res",
        "threshold_value": 220.0,
    }


def test_analyze_bone_microct_morphometry_defaults_threshold_to_none():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"bv_tv_fraction": 0.1})

    analyze_bone_microct_morphometry({"input_file_path": "microct/femur.nii.gz"}, driver)

    assert driver.last_args()["threshold_value"] is None


def test_analyze_bone_microct_morphometry_missing_input_file_path_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_bone_microct_morphometry({}, driver)
    assert driver.calls == []


def test_analyze_bone_microct_morphometry_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_bone_microct_morphometry({"input_file_path": "../../../etc/shadow"}, driver)
    assert driver.calls == []


# --- reconstruct_3d_face_from_mri -------------------------------------------


def test_reconstruct_3d_face_from_mri_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"vertex_count": 5000, "face_count": 9800})

    result = reconstruct_3d_face_from_mri(
        {
            "mri_file_path": "mri/subject01.nii.gz",
            "output_dir": "out",
            "subject_id": "subject01",
            "threshold_value": 300,
        },
        driver,
    )

    assert result == {"vertex_count": 5000, "face_count": 9800}
    args = driver.last_args()
    assert args["subject_id"] == "subject01"
    assert args["threshold_value"] == 300


def test_reconstruct_3d_face_from_mri_missing_mri_file_path_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        reconstruct_3d_face_from_mri({}, driver)
    assert driver.calls == []


def test_reconstruct_3d_face_from_mri_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        reconstruct_3d_face_from_mri({"mri_file_path": "/root/scan.nii.gz"}, driver)
    assert driver.calls == []


# --- analyze_abr_waveform_p1_metrics -----------------------------------------


def test_analyze_abr_waveform_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"p1_latency_ms": 1.6, "p1_amplitude_uv": 0.35})

    result = analyze_abr_waveform_p1_metrics(
        {"time_ms": [0.0, 0.5, 1.0, 1.5, 2.0], "amplitude_uv": [0.0, 0.1, 0.2, 0.35, 0.1]},
        driver,
    )

    assert result == {"p1_latency_ms": 1.6, "p1_amplitude_uv": 0.35}
    assert driver.last_args() == {
        "time_ms": [0.0, 0.5, 1.0, 1.5, 2.0],
        "amplitude_uv": [0.0, 0.1, 0.2, 0.35, 0.1],
    }


def test_analyze_abr_waveform_mismatched_lengths_raises_before_sandbox_call():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_abr_waveform_p1_metrics({"time_ms": [0.0, 1.0], "amplitude_uv": [0.1]}, driver)
    assert driver.calls == []


def test_analyze_abr_waveform_missing_field_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_abr_waveform_p1_metrics({"time_ms": [0.0, 1.0]}, driver)
    assert driver.calls == []


# --- analyze_ciliary_beat_frequency ------------------------------------------


def test_analyze_ciliary_beat_frequency_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"mean_beat_frequency_hz": 8.2})

    result = analyze_ciliary_beat_frequency(
        {
            "video_path": "videos/cilia.avi",
            "roi_count": 3,
            "min_freq": 2.0,
            "max_freq": 20.0,
            "output_dir": "out",
        },
        driver,
    )

    assert result == {"mean_beat_frequency_hz": 8.2}
    args = driver.last_args()
    assert args["roi_count"] == 3
    assert args["min_freq"] == 2.0
    assert args["max_freq"] == 20.0


def test_analyze_ciliary_beat_frequency_invalid_freq_range_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_ciliary_beat_frequency(
            {"video_path": "videos/cilia.avi", "min_freq": 20.0, "max_freq": 5.0}, driver
        )
    assert driver.calls == []


def test_analyze_ciliary_beat_frequency_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_ciliary_beat_frequency({"video_path": "..\\..\\cilia.avi"}, driver)
    assert driver.calls == []


# --- analyze_protein_colocalization ------------------------------------------


def test_analyze_protein_colocalization_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"pearson_r": 0.72})

    result = analyze_protein_colocalization(
        {"channel1_path": "ch/gfp.tif", "channel2_path": "ch/rfp.tif", "output_dir": "out"},
        driver,
    )

    assert result == {"pearson_r": 0.72}
    assert driver.last_args() == {
        "channel1_path": "ch/gfp.tif",
        "channel2_path": "ch/rfp.tif",
        "output_dir": "out",
        "threshold_method": "otsu",
    }


def test_analyze_protein_colocalization_missing_channel2_path_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_protein_colocalization({"channel1_path": "ch/gfp.tif"}, driver)
    assert driver.calls == []


def test_analyze_protein_colocalization_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_protein_colocalization(
            {"channel1_path": "ch/gfp.tif", "channel2_path": "../../ch/rfp.tif"}, driver
        )
    assert driver.calls == []


# --- perform_cosinor_analysis -------------------------------------------------


def test_perform_cosinor_analysis_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"mesor": 5.0, "amplitude": 1.2})

    result = perform_cosinor_analysis(
        {
            "time_data": [0, 4, 8, 12, 16, 20],
            "physiological_data": [5.0, 6.0, 5.5, 4.0, 3.8, 4.5],
            "period": 24.0,
        },
        driver,
    )

    assert result == {"mesor": 5.0, "amplitude": 1.2}
    args = driver.last_args()
    assert args["period"] == 24.0
    assert len(args["time_data"]) == 6


def test_perform_cosinor_analysis_too_few_points_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        perform_cosinor_analysis(
            {"time_data": [0, 4, 8], "physiological_data": [1.0, 2.0, 3.0]}, driver
        )
    assert driver.calls == []


def test_perform_cosinor_analysis_mismatched_lengths_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        perform_cosinor_analysis(
            {"time_data": [0, 4, 8, 12], "physiological_data": [1.0, 2.0, 3.0]}, driver
        )
    assert driver.calls == []


# --- calculate_brain_adc_map --------------------------------------------------


def test_calculate_brain_adc_map_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"mean_adc": 0.0008})

    result = calculate_brain_adc_map(
        {
            "dwi_file_path": "dwi/subject.nii.gz",
            "b_values": [0, 1000],
            "output_path": "adc/subject_adc.nii.gz",
            "mask_file_path": "dwi/brain_mask.nii.gz",
        },
        driver,
    )

    assert result == {"mean_adc": 0.0008}
    assert driver.last_args() == {
        "dwi_file_path": "dwi/subject.nii.gz",
        "b_values": [0, 1000],
        "output_path": "adc/subject_adc.nii.gz",
        "mask_file_path": "dwi/brain_mask.nii.gz",
    }


def test_calculate_brain_adc_map_no_mask_defaults_to_none():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"mean_adc": 0.0009})

    calculate_brain_adc_map({"dwi_file_path": "dwi/subject.nii.gz", "b_values": [0, 1000]}, driver)

    assert driver.last_args()["mask_file_path"] is None


def test_calculate_brain_adc_map_too_few_b_values_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        calculate_brain_adc_map({"dwi_file_path": "dwi/subject.nii.gz", "b_values": [0]}, driver)
    assert driver.calls == []


def test_calculate_brain_adc_map_path_traversal_in_mask_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        calculate_brain_adc_map(
            {
                "dwi_file_path": "dwi/subject.nii.gz",
                "b_values": [0, 1000],
                "mask_file_path": "../../etc/passwd",
            },
            driver,
        )
    assert driver.calls == []


# --- analyze_endolysosomal_calcium_dynamics -----------------------------------


def test_analyze_endolysosomal_calcium_dynamics_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"peak_value": 500.0, "decay_tau": 12.4})

    result = analyze_endolysosomal_calcium_dynamics(
        {
            "time_points": [0, 1, 2, 3, 4, 5],
            "luminescence_values": [100, 105, 500, 400, 300, 250],
            "treatment_time": 1.5,
            "cell_type": "HeLa",
            "treatment_name": "ionomycin",
            "output_file": "calcium_out.txt",
        },
        driver,
    )

    assert result == {"peak_value": 500.0, "decay_tau": 12.4}
    args = driver.last_args()
    assert args["treatment_time"] == 1.5
    assert args["cell_type"] == "HeLa"
    assert args["output_file"] == "calcium_out.txt"


def test_analyze_endolysosomal_calcium_dynamics_mismatched_lengths_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_endolysosomal_calcium_dynamics(
            {"time_points": [0, 1, 2], "luminescence_values": [1, 2]}, driver
        )
    assert driver.calls == []


def test_analyze_endolysosomal_calcium_dynamics_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_endolysosomal_calcium_dynamics(
            {
                "time_points": [0, 1, 2],
                "luminescence_values": [1, 2, 3],
                "output_file": "../../results.txt",
            },
            driver,
        )
    assert driver.calls == []


# --- analyze_fatty_acid_composition_by_gc -------------------------------------


def test_analyze_fatty_acid_composition_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"total_peak_area": 98765.0})

    result = analyze_fatty_acid_composition_by_gc(
        {
            "gc_data_file": "gc/sample1.csv",
            "tissue_type": "liver",
            "sample_id": "S001",
            "output_directory": "results",
        },
        driver,
    )

    assert result == {"total_peak_area": 98765.0}
    assert driver.last_args() == {
        "gc_data_file": "gc/sample1.csv",
        "tissue_type": "liver",
        "sample_id": "S001",
        "output_directory": "results",
    }


def test_analyze_fatty_acid_composition_missing_tissue_type_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_fatty_acid_composition_by_gc(
            {"gc_data_file": "gc/sample1.csv", "sample_id": "S001"}, driver
        )
    assert driver.calls == []


def test_analyze_fatty_acid_composition_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_fatty_acid_composition_by_gc(
            {"gc_data_file": "/etc/passwd", "tissue_type": "liver", "sample_id": "S001"}, driver
        )
    assert driver.calls == []


# --- analyze_hemodynamic_data --------------------------------------------------


def test_analyze_hemodynamic_data_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"mean_arterial_pressure": 93.3})

    result = analyze_hemodynamic_data(
        {
            "pressure_data": [80, 90, 120, 100, 82, 92, 121, 101],
            "sampling_rate": 100.0,
            "output_file": "hemo.csv",
        },
        driver,
    )

    assert result == {"mean_arterial_pressure": 93.3}
    args = driver.last_args()
    assert args["sampling_rate"] == 100.0
    assert args["output_file"] == "hemo.csv"


def test_analyze_hemodynamic_data_missing_sampling_rate_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        analyze_hemodynamic_data({"pressure_data": [80, 90, 100]}, driver)
    assert driver.calls == []


def test_analyze_hemodynamic_data_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        analyze_hemodynamic_data(
            {
                "pressure_data": [80, 90, 100],
                "sampling_rate": 100.0,
                "output_file": "../../out.csv",
            },
            driver,
        )
    assert driver.calls == []


# --- simulate_thyroid_hormone_pharmacokinetics --------------------------------


def test_simulate_thyroid_hormone_pharmacokinetics_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"compartments": ["central", "peripheral"]})

    result = simulate_thyroid_hormone_pharmacokinetics(
        {
            "parameters": {
                "transfer_rates": {"central->peripheral": 0.3, "peripheral->central": 0.2},
                "elimination_rates": {"central": 0.05},
            },
            "initial_conditions": {"central": 100.0, "peripheral": 0.0},
            "time_span": [0, 48],
            "time_points": 50,
        },
        driver,
    )

    assert result == {"compartments": ["central", "peripheral"]}
    args = driver.last_args()
    assert args["initial_conditions"] == {"central": 100.0, "peripheral": 0.0}
    assert args["time_span"] == [0.0, 48.0]
    assert args["time_points"] == 50


def test_simulate_thyroid_hormone_pharmacokinetics_missing_initial_conditions_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_thyroid_hormone_pharmacokinetics({"parameters": {}}, driver)
    assert driver.calls == []


def test_simulate_thyroid_hormone_pharmacokinetics_invalid_time_span_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        simulate_thyroid_hormone_pharmacokinetics(
            {"initial_conditions": {"central": 1.0}, "time_span": [24, 0]}, driver
        )
    assert driver.calls == []


# --- quantify_amyloid_beta_plaques ---------------------------------------------


def test_quantify_amyloid_beta_plaques_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"plaque_count": 42})

    result = quantify_amyloid_beta_plaques(
        {
            "image_path": "amyloid/section1.png",
            "output_dir": "res",
            "threshold_method": "manual",
            "min_plaque_size": 30,
            "manual_threshold": 140,
        },
        driver,
    )

    assert result == {"plaque_count": 42}
    args = driver.last_args()
    assert args["threshold_method"] == "manual"
    assert args["min_plaque_size"] == 30
    assert args["manual_threshold"] == 140


def test_quantify_amyloid_beta_plaques_missing_image_path_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        quantify_amyloid_beta_plaques({}, driver)
    assert driver.calls == []


def test_quantify_amyloid_beta_plaques_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        quantify_amyloid_beta_plaques({"image_path": "../../section1.png"}, driver)
    assert driver.calls == []


# --- decode_behavior_from_neural_trajectories ----------------------------------


def test_decode_behavior_from_neural_trajectories_valid_args_round_trip_and_parse_result():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"r_squared": 0.61})

    result = decode_behavior_from_neural_trajectories(
        {
            "neural_data": [[0.1, 0.2, 0.1], [0.3, 0.1, 0.4], [0.2, 0.5, 0.2], [0.4, 0.2, 0.3]],
            "behavioral_data": [1.0, 2.0, 1.5, 2.5],
            "n_components": 2,
            "output_dir": "res",
        },
        driver,
    )

    assert result == {"r_squared": 0.61}
    args = driver.last_args()
    assert args["n_components"] == 2
    assert args["behavioral_data"] == [1.0, 2.0, 1.5, 2.5]


def test_decode_behavior_from_neural_trajectories_mismatched_sample_counts_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        decode_behavior_from_neural_trajectories(
            {"neural_data": [[0.1, 0.2], [0.3, 0.4]], "behavioral_data": [1.0]}, driver
        )
    assert driver.calls == []


def test_decode_behavior_from_neural_trajectories_ragged_rows_raises():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        decode_behavior_from_neural_trajectories(
            {"neural_data": [[0.1, 0.2], [0.3, 0.4, 0.5]], "behavioral_data": [1.0, 2.0]}, driver
        )
    assert driver.calls == []


def test_decode_behavior_from_neural_trajectories_path_traversal_is_rejected():
    driver = FakeSandboxDriver()
    with pytest.raises(PathTraversalError):
        decode_behavior_from_neural_trajectories(
            {
                "neural_data": [[0.1, 0.2], [0.3, 0.4]],
                "behavioral_data": [1.0, 2.0],
                "output_dir": "../../results",
            },
            driver,
        )
    assert driver.calls == []


# --- registration --------------------------------------------------------------


def test_register_physiology_imaging_tools_registers_all_eighteen_tool_names():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()

    registered_names = register_physiology_imaging_tools(registry, driver)

    assert set(registered_names) == ALL_TOOL_NAMES
    assert len(ALL_TOOL_NAMES) == 18
    for name in ALL_TOOL_NAMES:
        assert name in registry.registry
        assert callable(registry.registry[name])


@pytest.mark.asyncio
async def test_registered_handler_routes_through_registry_and_calls_sandbox():
    registry = MCPServerRegistry()
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"p1_latency_ms": 1.6})
    register_physiology_imaging_tools(registry, driver)

    raw_result = await registry.route(
        "analyze_abr_waveform_p1_metrics",
        {"time_ms": [0.0, 1.0, 2.0], "amplitude_uv": [0.0, 0.4, 0.1]},
    )

    assert json.loads(raw_result) == {"p1_latency_ms": 1.6}
    assert len(driver.calls) == 1
