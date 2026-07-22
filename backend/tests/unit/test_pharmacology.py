"""Unit tests for the Drug discovery & pharmacology action tools
(`src/infrastructure/tools/pharmacology.py`). Per `_sandbox_tool_base.py`'s
module docstring, this repo's pytest venv has no scipy/rdkit/DeepPurpose/etc
-- these tests verify ARGUMENT VALIDATION + SCRIPT WIRING via
`FakeSandboxDriver`, not live numeric/scientific correctness."""
import json

import pytest
from pydantic import ValidationError

from src.infrastructure.tools import pharmacology as pharma
from src.infrastructure.tools._sandbox_tool_base import FakeSandboxDriver, NotSupportedError


# ---------------------------------------------------------------------------
# docking_autodock_vina
# ---------------------------------------------------------------------------


def test_docking_autodock_vina_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"docking_results": [{"smiles": "CCO", "best_binding_affinity_kcal_per_mol": -5.1}]})

    result = pharma.docking_autodock_vina(
        {
            "smiles_list": ["CCO"],
            "receptor_pdb_file": "receptors/target.pdb",
            "box_center": [1.0, 2.0, 3.0],
            "box_size": [20.0, 20.0, 20.0],
            "ncpu": 4,
        },
        driver,
    )

    assert result["docking_results"][0]["best_binding_affinity_kcal_per_mol"] == -5.1
    sent_args = driver.last_args()
    assert sent_args["receptor_pdb_file"] == "receptors/target.pdb"
    assert sent_args["box_center"] == [1.0, 2.0, 3.0]
    assert sent_args["ncpu"] == 4


def test_docking_autodock_vina_rejects_missing_required_args_before_sandbox():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.docking_autodock_vina({"smiles_list": ["CCO"]}, driver)
    assert driver.calls == []


def test_docking_autodock_vina_rejects_bad_box_center_length():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.docking_autodock_vina(
            {
                "smiles_list": ["CCO"],
                "receptor_pdb_file": "target.pdb",
                "box_center": [1.0, 2.0],
                "box_size": [20.0, 20.0, 20.0],
            },
            driver,
        )
    assert driver.calls == []


def test_docking_autodock_vina_rejects_path_traversal_receptor():
    driver = FakeSandboxDriver()
    with pytest.raises(ValueError):
        pharma.docking_autodock_vina(
            {
                "smiles_list": ["CCO"],
                "receptor_pdb_file": "../../etc/passwd",
                "box_center": [1.0, 2.0, 3.0],
                "box_size": [20.0, 20.0, 20.0],
            },
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# run_autosite
# ---------------------------------------------------------------------------


def test_run_autosite_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"predicted_pocket_files": ["receptor_cl_1.pdb"]})

    result = pharma.run_autosite(
        {"pdb_file": "structures/target.pdb", "output_dir": "autosite_out", "spacing": 0.5}, driver,
    )

    assert result["predicted_pocket_files"] == ["receptor_cl_1.pdb"]
    sent_args = driver.last_args()
    assert sent_args["pdb_file"] == "structures/target.pdb"
    assert sent_args["spacing"] == 0.5


def test_run_autosite_rejects_missing_pdb_file():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.run_autosite({"output_dir": "out"}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# calculate_physicochemical_properties
# ---------------------------------------------------------------------------


def test_calculate_physicochemical_properties_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"molecular_weight": 46.07, "logp": -0.0014})

    result = pharma.calculate_physicochemical_properties({"smiles_string": "CCO"}, driver)

    assert result["molecular_weight"] == 46.07
    assert driver.last_args() == {"smiles_string": "CCO"}


def test_calculate_physicochemical_properties_rejects_empty_smiles():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.calculate_physicochemical_properties({"smiles_string": "   "}, driver)
    assert driver.calls == []


def test_calculate_physicochemical_properties_rejects_missing_smiles():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.calculate_physicochemical_properties({}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_accelerated_stability_of_pharmaceutical_formulations
# ---------------------------------------------------------------------------


def _stability_args(**overrides):
    base = {
        "formulations": [
            {"name": "Formulation A", "percent_remaining": [[100, 95, 89], [100, 99, 97]]},
        ],
        "storage_conditions": [{"temperature_C": 40}, {"temperature_C": 25}],
        "time_points": [0, 3, 6],
    }
    base.update(overrides)
    return base


def test_analyze_accelerated_stability_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"formulation_results": [{"formulation": "Formulation A"}]})

    result = pharma.analyze_accelerated_stability_of_pharmaceutical_formulations(
        _stability_args(), driver,
    )

    assert result["formulation_results"][0]["formulation"] == "Formulation A"
    sent_args = driver.last_args()
    assert sent_args["time_points"] == [0, 3, 6]
    assert len(sent_args["storage_conditions"]) == 2


def test_analyze_accelerated_stability_rejects_mismatched_series_length():
    driver = FakeSandboxDriver()
    bad_args = _stability_args(
        formulations=[{"name": "F1", "percent_remaining": [[100, 95, 89]]}],  # only 1 condition series
    )
    with pytest.raises(ValidationError):
        pharma.analyze_accelerated_stability_of_pharmaceutical_formulations(bad_args, driver)
    assert driver.calls == []


def test_analyze_accelerated_stability_rejects_single_storage_condition():
    driver = FakeSandboxDriver()
    bad_args = _stability_args(storage_conditions=[{"temperature_C": 40}])
    with pytest.raises(ValidationError):
        pharma.analyze_accelerated_stability_of_pharmaceutical_formulations(bad_args, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# run_3d_chondrogenic_aggregate_assay
# ---------------------------------------------------------------------------


def test_run_3d_chondrogenic_aggregate_assay_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"protocol_steps": [{"step": 1}]})

    result = pharma.run_3d_chondrogenic_aggregate_assay(
        {
            "chondrocyte_cells": {"cell_type": "primary chondrocytes", "cell_count": "2.5e5"},
            "test_compounds": ["IL-1beta", "Compound-X"],
            "culture_duration_days": 14,
            "measurement_intervals": 7,
        },
        driver,
    )

    assert result["protocol_steps"] == [{"step": 1}]
    sent_args = driver.last_args()
    assert sent_args["culture_duration_days"] == 14
    assert sent_args["test_compounds"] == ["IL-1beta", "Compound-X"]


def test_run_3d_chondrogenic_aggregate_assay_rejects_empty_compounds():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.run_3d_chondrogenic_aggregate_assay(
            {"chondrocyte_cells": {}, "test_compounds": []}, driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# grade_adverse_events_using_vcog_ctcae
# ---------------------------------------------------------------------------


def test_grade_adverse_events_using_vcog_ctcae_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"num_graded": 3, "num_ungraded": 0})

    result = pharma.grade_adverse_events_using_vcog_ctcae(
        {"clinical_data_file": "clinical/patient_labs.csv"}, driver,
    )

    assert result["num_graded"] == 3
    sent_args = driver.last_args()
    assert sent_args["clinical_data_file"] == "clinical/patient_labs.csv"
    assert "neutropenia" in sent_args["grading_table"]


def test_grade_adverse_events_using_vcog_ctcae_rejects_missing_file_arg():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.grade_adverse_events_using_vcog_ctcae({}, driver)
    assert driver.calls == []


def test_grade_adverse_events_using_vcog_ctcae_rejects_absolute_path():
    driver = FakeSandboxDriver()
    with pytest.raises(ValueError):
        pharma.grade_adverse_events_using_vcog_ctcae({"clinical_data_file": "/etc/passwd"}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_radiolabeled_antibody_biodistribution
# ---------------------------------------------------------------------------


def test_analyze_radiolabeled_antibody_biodistribution_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"per_tissue_pharmacokinetics": {"tumor": {"cmax": 10.0}}})

    result = pharma.analyze_radiolabeled_antibody_biodistribution(
        {
            "time_points": [1, 4, 24, 48],
            "tissue_data": {
                "tumor": [5.0, 8.0, 10.0, 6.0],
                "liver": [3.0, 4.0, 2.0, 1.0],
            },
        },
        driver,
    )

    assert result["per_tissue_pharmacokinetics"]["tumor"]["cmax"] == 10.0
    sent_args = driver.last_args()
    assert sent_args["tissue_data"]["tumor"] == [5.0, 8.0, 10.0, 6.0]


def test_analyze_radiolabeled_antibody_biodistribution_requires_tumor_key():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.analyze_radiolabeled_antibody_biodistribution(
            {"time_points": [1, 4], "tissue_data": {"liver": [3.0, 4.0]}}, driver,
        )
    assert driver.calls == []


def test_analyze_radiolabeled_antibody_biodistribution_rejects_length_mismatch():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.analyze_radiolabeled_antibody_biodistribution(
            {"time_points": [1, 4, 24], "tissue_data": {"tumor": [5.0, 8.0]}}, driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# estimate_alpha_particle_radiotherapy_dosimetry
# ---------------------------------------------------------------------------


def _dosimetry_args(**overrides):
    base = {
        "biodistribution_data": {
            "tumor": {"time_hr": [1, 24, 48], "activity_MBq": [10.0, 5.0, 2.0], "mass_g": 2.0},
        },
        "radiation_parameters": {"energy_per_decay_MeV": 6.0},
    }
    base.update(overrides)
    return base


def test_estimate_alpha_particle_radiotherapy_dosimetry_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"per_tissue_dosimetry": {"tumor": {"absorbed_dose_Gy": 1.23}}})

    result = pharma.estimate_alpha_particle_radiotherapy_dosimetry(_dosimetry_args(), driver)

    assert result["per_tissue_dosimetry"]["tumor"]["absorbed_dose_Gy"] == 1.23
    sent_args = driver.last_args()
    assert sent_args["radiation_parameters"]["energy_per_decay_mev"] == 6.0
    assert sent_args["output_file"] == "dosimetry_results.csv"


def test_estimate_alpha_particle_radiotherapy_dosimetry_requires_energy_param():
    driver = FakeSandboxDriver()
    bad_args = _dosimetry_args(radiation_parameters={"absorbed_fraction": 1.0})
    with pytest.raises(ValidationError):
        pharma.estimate_alpha_particle_radiotherapy_dosimetry(bad_args, driver)
    assert driver.calls == []


def test_estimate_alpha_particle_radiotherapy_dosimetry_rejects_mismatched_series():
    driver = FakeSandboxDriver()
    bad_args = _dosimetry_args(
        biodistribution_data={
            "tumor": {"time_hr": [1, 24], "activity_MBq": [10.0], "mass_g": 2.0},
        },
    )
    with pytest.raises(ValidationError):
        pharma.estimate_alpha_particle_radiotherapy_dosimetry(bad_args, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# perform_mwas_cyp2c19_metabolizer_status
# ---------------------------------------------------------------------------


def test_perform_mwas_cyp2c19_metabolizer_status_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"n_significant": 2})

    result = pharma.perform_mwas_cyp2c19_metabolizer_status(
        {
            "methylation_data_path": "methylation/beta_values.csv",
            "metabolizer_status_path": "phenotype/status.csv",
            "pvalue_threshold": 0.01,
        },
        driver,
    )

    assert result["n_significant"] == 2
    sent_args = driver.last_args()
    assert sent_args["pvalue_threshold"] == 0.01
    assert sent_args["covariates_path"] is None


def test_perform_mwas_cyp2c19_metabolizer_status_rejects_bad_pvalue_threshold():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.perform_mwas_cyp2c19_metabolizer_status(
            {
                "methylation_data_path": "a.csv",
                "metabolizer_status_path": "b.csv",
                "pvalue_threshold": 1.5,
            },
            driver,
        )
    assert driver.calls == []


def test_perform_mwas_cyp2c19_metabolizer_status_rejects_path_traversal_covariates():
    driver = FakeSandboxDriver()
    with pytest.raises(ValueError):
        pharma.perform_mwas_cyp2c19_metabolizer_status(
            {
                "methylation_data_path": "a.csv",
                "metabolizer_status_path": "b.csv",
                "covariates_path": "../secrets.csv",
            },
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_xenograft_tumor_growth_inhibition
# ---------------------------------------------------------------------------


def test_analyze_xenograft_tumor_growth_inhibition_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"tumor_growth_inhibition_percent": [{"group": "treated", "tgi_percent": 40.0}]})

    result = pharma.analyze_xenograft_tumor_growth_inhibition(
        {
            "data_path": "xenograft/volumes.csv",
            "time_column": "day",
            "volume_column": "volume_mm3",
            "group_column": "arm",
            "subject_column": "mouse_id",
        },
        driver,
    )

    assert result["tumor_growth_inhibition_percent"][0]["tgi_percent"] == 40.0
    sent_args = driver.last_args()
    assert sent_args["output_dir"] == "results"
    assert sent_args["time_column"] == "day"


def test_analyze_xenograft_tumor_growth_inhibition_rejects_missing_columns():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.analyze_xenograft_tumor_growth_inhibition(
            {"data_path": "xenograft/volumes.csv", "time_column": "day"}, driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# analyze_western_blot
# ---------------------------------------------------------------------------


def test_analyze_western_blot_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"target_bands": [{"name": "p53", "normalized_to_loading_control": 1.5}]})

    result = pharma.analyze_western_blot(
        {
            "blot_image_path": "blots/exp1.png",
            "target_bands": [{"name": "p53", "expected_kda": 53, "position": [10, 20, 60, 40]}],
            "loading_control_band": {"name": "GAPDH", "position": [10, 200, 60, 220]},
            "antibody_info": {"p53": "anti-p53, 1:1000"},
        },
        driver,
    )

    assert result["target_bands"][0]["normalized_to_loading_control"] == 1.5
    sent_args = driver.last_args()
    assert sent_args["blot_image_path"] == "blots/exp1.png"
    assert sent_args["output_dir"] == "results"


def test_analyze_western_blot_rejects_band_without_position():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.analyze_western_blot(
            {
                "blot_image_path": "blots/exp1.png",
                "target_bands": [{"name": "p53"}],
                "loading_control_band": {"name": "GAPDH", "position": [10, 200, 60, 220]},
            },
            driver,
        )
    assert driver.calls == []


def test_analyze_western_blot_rejects_control_band_without_position():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.analyze_western_blot(
            {
                "blot_image_path": "blots/exp1.png",
                "target_bands": [{"name": "p53", "position": [10, 20, 60, 40]}],
                "loading_control_band": {"name": "GAPDH"},
            },
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# predict_admet_properties (network-access exception)
# ---------------------------------------------------------------------------


def test_predict_admet_properties_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"predictions_per_smiles": {"CCO": {"Caco2_Wang": -4.5}}})

    result = pharma.predict_admet_properties({"smiles_list": ["CCO"], "ADMET_model_type": "MPNN"}, driver)

    assert result["predictions_per_smiles"]["CCO"]["Caco2_Wang"] == -4.5
    sent_args = driver.last_args()
    assert sent_args["smiles_list"] == ["CCO"]
    assert sent_args["admet_model_type"] == "MPNN"


def test_predict_admet_properties_uses_network_enabled_driver():
    driver = FakeSandboxDriver()
    assert not getattr(driver, "allow_network", False)

    pharma.predict_admet_properties({"smiles_list": ["CCO"]}, driver)

    assert driver.allow_network is True


def test_predict_admet_properties_rejects_invalid_model_type():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.predict_admet_properties({"smiles_list": ["CCO"], "ADMET_model_type": "not-a-real-encoding"}, driver)
    assert driver.calls == []


def test_predict_admet_properties_rejects_empty_smiles_list():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.predict_admet_properties({"smiles_list": []}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# predict_binding_affinity_protein_1d_sequence (network-access exception)
# ---------------------------------------------------------------------------


def test_predict_binding_affinity_round_trips_valid_args():
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"predictions": [{"smiles": "CCO", "predicted_binding_affinity_pKd": 7.1}]})

    result = pharma.predict_binding_affinity_protein_1d_sequence(
        {"smiles_list": ["CCO"], "amino_acid_sequence": "MKKFFDS", "affinity_model_type": "MPNN-CNN"},
        driver,
    )

    assert result["predictions"][0]["predicted_binding_affinity_pKd"] == 7.1
    sent_args = driver.last_args()
    assert sent_args["pretrained_model_name"] == "MPNN_CNN_BindingDB"
    assert sent_args["amino_acid_sequence"] == "MKKFFDS"


def test_predict_binding_affinity_uses_network_enabled_driver():
    driver = FakeSandboxDriver()
    assert not getattr(driver, "allow_network", False)

    pharma.predict_binding_affinity_protein_1d_sequence(
        {"smiles_list": ["CCO"], "amino_acid_sequence": "MKKFFDS"}, driver,
    )

    assert driver.allow_network is True


def test_predict_binding_affinity_rejects_missing_sequence():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.predict_binding_affinity_protein_1d_sequence({"smiles_list": ["CCO"]}, driver)
    assert driver.calls == []


def test_predict_binding_affinity_rejects_invalid_model_type():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.predict_binding_affinity_protein_1d_sequence(
            {"smiles_list": ["CCO"], "amino_acid_sequence": "MKKFFDS", "affinity_model_type": "bogus"},
            driver,
        )
    assert driver.calls == []


# ---------------------------------------------------------------------------
# run_diffdock_with_smiles -- Tier D
# ---------------------------------------------------------------------------


def test_run_diffdock_with_smiles_raises_not_supported():
    driver = FakeSandboxDriver()
    with pytest.raises(NotSupportedError, match="UNSUPPORTED.md"):
        pharma.run_diffdock_with_smiles(
            {
                "pdb_path": "structures/target.pdb",
                "smiles_string": "CCO",
                "local_output_dir": "diffdock_out",
            },
            driver,
        )
    assert driver.calls == []


def test_run_diffdock_with_smiles_is_a_notimplementederror():
    driver = FakeSandboxDriver()
    with pytest.raises(NotImplementedError):
        pharma.run_diffdock_with_smiles(
            {"pdb_path": "t.pdb", "smiles_string": "CCO", "local_output_dir": "out"}, driver,
        )


def test_run_diffdock_with_smiles_still_validates_args_first():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.run_diffdock_with_smiles({"smiles_string": "CCO"}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# retrieve_topk_repurposing_drugs_from_disease_txgnn -- Tier D
# ---------------------------------------------------------------------------


def test_retrieve_topk_repurposing_drugs_from_disease_txgnn_raises_not_supported():
    driver = FakeSandboxDriver()
    with pytest.raises(NotSupportedError, match="UNSUPPORTED.md"):
        pharma.retrieve_topk_repurposing_drugs_from_disease_txgnn(
            {"disease_name": "pancreatic cancer", "k": 5}, driver,
        )
    assert driver.calls == []


def test_retrieve_topk_repurposing_drugs_from_disease_txgnn_is_a_notimplementederror():
    driver = FakeSandboxDriver()
    with pytest.raises(NotImplementedError):
        pharma.retrieve_topk_repurposing_drugs_from_disease_txgnn({"disease_name": "asthma"}, driver)


def test_retrieve_topk_repurposing_drugs_from_disease_txgnn_rejects_empty_disease_name():
    driver = FakeSandboxDriver()
    with pytest.raises(ValidationError):
        pharma.retrieve_topk_repurposing_drugs_from_disease_txgnn({"disease_name": "  "}, driver)
    assert driver.calls == []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class _FakeRegistry:
    def __init__(self):
        self.registered = {}

    def register_server(self, name, handler):
        self.registered[name] = handler


def test_register_pharmacology_tools_registers_every_tool():
    registry = _FakeRegistry()
    driver = FakeSandboxDriver()

    names = pharma.register_pharmacology_tools(registry, driver)

    expected = {
        "docking_autodock_vina",
        "run_autosite",
        "calculate_physicochemical_properties",
        "analyze_accelerated_stability_of_pharmaceutical_formulations",
        "run_3d_chondrogenic_aggregate_assay",
        "grade_adverse_events_using_vcog_ctcae",
        "analyze_radiolabeled_antibody_biodistribution",
        "estimate_alpha_particle_radiotherapy_dosimetry",
        "perform_mwas_cyp2c19_metabolizer_status",
        "analyze_xenograft_tumor_growth_inhibition",
        "analyze_western_blot",
        "predict_admet_properties",
        "predict_binding_affinity_protein_1d_sequence",
        "run_diffdock_with_smiles",
        "retrieve_topk_repurposing_drugs_from_disease_txgnn",
    }
    assert set(names) == expected
    assert set(registry.registered.keys()) == expected
    for handler in registry.registered.values():
        assert callable(handler)


def test_register_pharmacology_tools_handlers_are_callable_via_registry():
    registry = _FakeRegistry()
    driver = FakeSandboxDriver()
    driver.stdout = json.dumps({"molecular_weight": 46.07})
    pharma.register_pharmacology_tools(registry, driver)

    result = registry.registered["calculate_physicochemical_properties"]({"smiles_string": "CCO"})

    assert result["molecular_weight"] == 46.07


# ---------------------------------------------------------------------------
# _network_enabled_driver helper (network-access exception plumbing)
# ---------------------------------------------------------------------------


def test_network_enabled_driver_reuses_already_network_enabled_driver():
    driver = FakeSandboxDriver()
    driver.allow_network = True

    returned = pharma._network_enabled_driver(driver)

    assert returned is driver


def test_network_enabled_driver_flags_fake_driver_in_place():
    driver = FakeSandboxDriver()

    returned = pharma._network_enabled_driver(driver)

    assert returned is driver
    assert driver.allow_network is True
