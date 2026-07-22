"""Drug discovery & pharmacology action tools (Fase 5).

Implements every tool listed under the "Categoria: Drug discovery &
pharmacology" heading of `backend/docs/tools/action_tool_catalog.md`. Every
Tier A/B/C tool runs its real scientific logic inside the sandbox via
`run_in_sandbox` (see `_sandbox_tool_base.py`'s module docstring for exactly
why); the two Tier D tools raise `NotSupportedError` directly, no sandbox
call at all.

Per-tool tiering (see `action_tool_catalog.md` for the authoritative source,
this is a recap, not a re-derivation):

- Tier A: `docking_autodock_vina` (real AutoDock Vina python bindings, ligand
  3D-embedded/optimized with RDKit then converted to PDBQT via `obabel`),
  `run_autosite` (real ADFRsuite `prepare_receptor`/`autosite` CLI binding
  detection), `calculate_physicochemical_properties` (real RDKit
  descriptors), `run_3d_chondrogenic_aggregate_assay` (structured wet-lab
  protocol generator, no numeric simulation), `grade_adverse_events_using_
  vcog_ctcae` (rule-table lookup against a small bundled illustrative subset
  of VCOG-CTCAE v2 hematologic/GI grading thresholds -- NOT the full official
  table; an unrecognized adverse-event term is reported as ungraded rather
  than assigned a fabricated grade).
- Tier B: `predict_admet_properties` / `predict_binding_affinity_protein_
  1d_sequence` (real DeepPurpose calls, see the network-access note below),
  `analyze_accelerated_stability_of_pharmaceutical_formulations` (real
  Arrhenius-equation fit via `scipy.stats.linregress`),
  `analyze_radiolabeled_antibody_biodistribution` (real per-tissue
  biexponential PK fit via `scipy.optimize.curve_fit` + trapezoidal AUC;
  untagged in the catalog but a curve-fitting method per the tiering
  rubric's own Tier B definition), `estimate_alpha_particle_radiotherapy_
  dosimetry` (real closed-form MIRD-schema dose calculation),
  `perform_mwas_cyp2c19_metabolizer_status` (real per-CpG-site OLS regression
  + Benjamini-Hochberg FDR correction via `statsmodels`),
  `analyze_xenograft_tumor_growth_inhibition` (real per-subject exponential
  growth-rate fit via `scipy.stats.linregress` + group comparison test).
- Tier C: `analyze_western_blot` (general-purpose scikit-image densitometric
  quantification -- documented in its own docstring, per the catalog's
  cross-cutting note, as a general image-processing method, NOT clinically
  or publication-validated blot-quantification software).
- Tier D: `run_diffdock_with_smiles` (DiffDock needs its own pretrained
  diffusion-model checkpoint + GPU + its own Docker container) and
  `retrieve_topk_repurposing_drugs_from_disease_txgnn` (TxGNN needs a trained
  checkpoint over a specific knowledge-graph snapshot this deployment does
  not have). Both are already listed in `backend/docs/tools/UNSUPPORTED.md`
  -- no new row needed.

NETWORK-ACCESS EXCEPTION (`predict_admet_properties` /
`predict_binding_affinity_protein_1d_sequence` ONLY): every other tool in
this module runs against the shared, network-isolated `driver` it was
registered with (`--unshare-net`, see `bubblewrap_driver.py`). These two
DeepPurpose-backed tools are the sole exception in this whole category:

- `predict_binding_affinity_protein_1d_sequence` loads a DeepPurpose DTI
  pretrained checkpoint (`models.model_pretrained(model=...)`) -- on a fresh
  deployment this downloads real weights from DeepPurpose's model zoo the
  first time a given `affinity_model_type` is requested.
- `predict_admet_properties` has no single bundled "ADMET checkpoint" to
  download at all (DeepPurpose's own documented ADMET workflow is
  train-a-small-`CompoundPred`-model-on-real-TDC-`ADMET_Group`-data, not
  load-a-universal-pretrained-model -- see this tool's own docstring) -- it
  fetches real TDC benchmark data over the network EVERY call, not just the
  first one, since this sandbox has no writable, persistent location to
  cache a trained model across separate `run_in_sandbox` invocations
  (`/workspace` is read-only, `/tmp` is a fresh tmpfs per call). This is a
  more precise, honest restatement of `UNSUPPORTED.md`'s "first call"
  framing for this specific tool -- flagged here rather than silently
  glossed over.

Both handlers therefore call `_network_enabled_driver(driver)` to run against
a driver with `allow_network=True` (and a much larger CPU/wall-clock budget,
see `_NETWORK_TOOL_*_SECONDS`) instead of the shared, network-isolated
`driver` every other tool in this module uses.

Every file-path-shaped argument (`receptor_pdb_file`, `pdb_file`,
`output_dir`, `clinical_data_file`, `output_file`, `*_path`) is passed
through `ensure_safe_relative_path` before being handed to the sandbox.
"""
import functools
import textwrap
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.domain.services.path_guard import ensure_safe_relative_path
from src.infrastructure.sandbox.bubblewrap_driver import BubblewrapSandboxDriver
from src.infrastructure.tools._sandbox_tool_base import NotSupportedError, run_in_sandbox


def _dedent(script: str) -> str:
    """Strips this module's Python-source indentation off a `script_body`
    literal so the code that actually reaches the sandbox starts every line
    at column 0 (required -- `run_in_sandbox` concatenates `script_body`
    directly after its own top-level `_args` loading preamble)."""
    return textwrap.dedent(script).strip("\n")


# ---------------------------------------------------------------------------
# Network-access exception plumbing (see module docstring).
# ---------------------------------------------------------------------------

# Real outbound HTTP is unavoidable for the two DeepPurpose-backed tools
# below (pretrained-weight download for the affinity tool; PyTDC's real
# ADMET_Group benchmark-data download + a quick from-scratch model fit for
# the ADMET tool, see each handler's own docstring) -- give both a much
# larger budget than every other (network-isolated, fast) tool in this
# category gets.
_NETWORK_TOOL_CPU_SECONDS = 1800
_NETWORK_TOOL_TIMEOUT_SECONDS = 1800


def _network_enabled_driver(driver):
    """Returns a sandbox driver with outbound network access enabled, for
    `predict_admet_properties` / `predict_binding_affinity_protein_1d_sequence`
    ONLY (see module docstring) -- every other tool in this category keeps
    using the shared, network-isolated `driver` it was registered with.

    - If `driver` already allows network, it is reused unchanged.
    - If `driver` is a real `BubblewrapSandboxDriver`, a NEW instance of the
      same class is constructed, copying over its other configured settings
      but with `allow_network=True` and a raised CPU/wall-clock budget (see
      `_NETWORK_TOOL_*_SECONDS`) -- building a fresh driver rather than
      mutating the shared one keeps every other tool's `--unshare-net`
      isolation intact.
    - Otherwise (a test double such as `FakeSandboxDriver`, which never
      enforces network isolation at all since it never really executes
      `script_body`) the `allow_network` attribute is simply set on the same
      object and it is reused, so a unit test can assert on it directly
      without ever importing the real bwrap driver.
    """
    if getattr(driver, "allow_network", False):
        return driver
    if isinstance(driver, BubblewrapSandboxDriver):
        return BubblewrapSandboxDriver(
            workspace_root=driver.workspace_root,
            tracer=driver.tracer,
            runtime=driver.runtime,
            allow_network=True,
            cpu_seconds=max(driver.cpu_seconds, _NETWORK_TOOL_CPU_SECONDS),
            memory_bytes=driver.memory_bytes,
            timeout_seconds=max(driver.timeout_seconds, _NETWORK_TOOL_TIMEOUT_SECONDS),
            data_lake_root=driver.data_lake_root,
        )
    driver.allow_network = True
    return driver


# ---------------------------------------------------------------------------
# docking_autodock_vina
# ---------------------------------------------------------------------------


class DockingAutodockVinaArgs(BaseModel):
    smiles_list: List[str] = Field(min_length=1)
    receptor_pdb_file: str
    box_center: List[float]
    box_size: List[float]
    ncpu: int = Field(default=1, gt=0)

    @field_validator("smiles_list")
    @classmethod
    def _non_empty_smiles(cls, value: List[str]) -> List[str]:
        cleaned = [s.strip() for s in value]
        if any(not s for s in cleaned):
            raise ValueError("smiles_list must not contain empty strings")
        return cleaned

    @field_validator("box_center", "box_size")
    @classmethod
    def _exactly_three_coordinates(cls, value: List[float]) -> List[float]:
        if len(value) != 3:
            raise ValueError("must have exactly 3 elements ([x, y, z])")
        return value


def docking_autodock_vina(arguments: dict, driver) -> dict:
    """Real AutoDock Vina docking: each SMILES is embedded to 3D and
    MMFF-optimized with RDKit, converted to PDBQT via `obabel` (argv-list
    subprocess call), and docked against `receptor_pdb_file` (also converted
    to PDBQT via `obabel`) with the real `vina` Python bindings
    (`Vina.compute_vina_maps` + `Vina.dock`), returning each ligand's best
    predicted binding affinity in kcal/mol."""
    validated = DockingAutodockVinaArgs.model_validate(arguments or {})
    receptor_pdb_file = ensure_safe_relative_path(validated.receptor_pdb_file)

    script_body = _dedent(
        """
        import json
        import os
        import subprocess

        from rdkit import Chem
        from rdkit.Chem import AllChem
        from vina import Vina

        receptor_pdb_file = _args["receptor_pdb_file"]
        smiles_list = _args["smiles_list"]
        box_center = _args["box_center"]
        box_size = _args["box_size"]
        ncpu = int(_args["ncpu"])

        work_dir = "/tmp/docking_autodock_vina"
        os.makedirs(work_dir, exist_ok=True)

        receptor_pdbqt = os.path.join(work_dir, "receptor.pdbqt")
        proc = subprocess.run(
            ["obabel", receptor_pdb_file, "-O", receptor_pdbqt, "-xr"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not os.path.exists(receptor_pdbqt):
            raise RuntimeError(f"obabel failed to prepare the receptor: {proc.stderr}")

        docking_results = []
        for idx, smiles in enumerate(smiles_list):
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                docking_results.append({"smiles": smiles, "error": "invalid SMILES"})
                continue
            mol = Chem.AddHs(mol)
            if AllChem.EmbedMolecule(mol, randomSeed=42) != 0:
                docking_results.append({"smiles": smiles, "error": "3D embedding failed"})
                continue
            AllChem.MMFFOptimizeMolecule(mol)

            ligand_pdb = os.path.join(work_dir, f"ligand_{idx}.pdb")
            Chem.MolToPDBFile(mol, ligand_pdb)
            ligand_pdbqt = os.path.join(work_dir, f"ligand_{idx}.pdbqt")
            proc = subprocess.run(
                ["obabel", ligand_pdb, "-O", ligand_pdbqt], capture_output=True, text=True,
            )
            if proc.returncode != 0 or not os.path.exists(ligand_pdbqt):
                docking_results.append({
                    "smiles": smiles, "error": f"obabel failed to prepare ligand: {proc.stderr}",
                })
                continue

            v = Vina(sf_name="vina", cpu=ncpu, verbosity=0)
            v.set_receptor(receptor_pdbqt)
            v.set_ligand_from_file(ligand_pdbqt)
            v.compute_vina_maps(center=box_center, box_size=box_size)
            v.dock(exhaustiveness=8, n_poses=9)
            energies = v.energies(n_poses=9)
            out_pdbqt = os.path.join(work_dir, f"ligand_{idx}_out.pdbqt")
            v.write_poses(out_pdbqt, n_poses=1, overwrite=True)

            docking_results.append({
                "smiles": smiles,
                "best_binding_affinity_kcal_per_mol": float(energies[0][0]) if len(energies) else None,
                "num_poses": len(energies),
                "output_pdbqt": out_pdbqt,
            })

        result = {
            "receptor_pdb_file": receptor_pdb_file,
            "box_center": box_center,
            "box_size": box_size,
            "ncpu": ncpu,
            "docking_results": docking_results,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "smiles_list": validated.smiles_list,
        "receptor_pdb_file": receptor_pdb_file,
        "box_center": validated.box_center,
        "box_size": validated.box_size,
        "ncpu": validated.ncpu,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# run_autosite
# ---------------------------------------------------------------------------


class RunAutositeArgs(BaseModel):
    pdb_file: str
    output_dir: str
    spacing: float = Field(default=1.0, gt=0)


def run_autosite(arguments: dict, driver) -> dict:
    """Real AutoSite binding-site detection via the ADFRsuite CLI:
    `prepare_receptor` converts `pdb_file` to PDBQT, then `autosite` scans it
    for candidate binding pockets at the requested grid `spacing`. Both
    external tools are invoked via argv-list `subprocess.run` calls, never a
    shell string."""
    validated = RunAutositeArgs.model_validate(arguments or {})
    pdb_file = ensure_safe_relative_path(validated.pdb_file)
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os
        import subprocess

        pdb_file = _args["pdb_file"]
        output_dir = _args["output_dir"]
        spacing = float(_args["spacing"])

        os.makedirs(output_dir, exist_ok=True)

        receptor_pdbqt = os.path.join(output_dir, "receptor.pdbqt")
        proc = subprocess.run(
            ["prepare_receptor", "-r", pdb_file, "-o", receptor_pdbqt],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not os.path.exists(receptor_pdbqt):
            raise RuntimeError(f"prepare_receptor failed: {proc.stderr}")

        proc = subprocess.run(
            ["autosite", "-r", receptor_pdbqt, "-o", output_dir, "-s", str(spacing)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"autosite failed: {proc.stderr}")

        predicted_pocket_files = sorted(
            f for f in os.listdir(output_dir)
            if f != os.path.basename(receptor_pdbqt) and ("cl" in f.lower() or "pocket" in f.lower())
        )

        result = {
            "pdb_file": pdb_file,
            "output_dir": output_dir,
            "spacing": spacing,
            "receptor_pdbqt": receptor_pdbqt,
            "autosite_stdout": proc.stdout,
            "predicted_pocket_files": predicted_pocket_files,
        }
        print(json.dumps(result))
        """
    )
    args = {"pdb_file": pdb_file, "output_dir": output_dir, "spacing": validated.spacing}
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# calculate_physicochemical_properties
# ---------------------------------------------------------------------------


class CalculatePhysicochemicalPropertiesArgs(BaseModel):
    smiles_string: str

    @field_validator("smiles_string")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("smiles_string must be a non-empty string")
        return value


def calculate_physicochemical_properties(arguments: dict, driver) -> dict:
    """Real RDKit physicochemical descriptors (molecular weight, LogP, TPSA,
    H-bond donor/acceptor counts, rotatable bonds, ring counts, molecular
    formula, QED, and a Lipinski rule-of-five violation count) for a single
    SMILES string."""
    validated = CalculatePhysicochemicalPropertiesArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors

        smiles = _args["smiles_string"]
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES string: {smiles!r}")

        molecular_weight = Descriptors.MolWt(mol)
        logp = Crippen.MolLogP(mol)
        num_h_donors = Lipinski.NumHDonors(mol)
        num_h_acceptors = Lipinski.NumHAcceptors(mol)

        result = {
            "smiles": smiles,
            "molecular_weight": molecular_weight,
            "logp": logp,
            "tpsa": rdMolDescriptors.CalcTPSA(mol),
            "num_h_donors": num_h_donors,
            "num_h_acceptors": num_h_acceptors,
            "num_rotatable_bonds": Descriptors.NumRotatableBonds(mol),
            "num_rings": rdMolDescriptors.CalcNumRings(mol),
            "num_aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
            "molar_refractivity": Crippen.MolMR(mol),
            "molecular_formula": rdMolDescriptors.CalcMolFormula(mol),
            "qed": Descriptors.qed(mol),
            "lipinski_rule_of_five_violations": sum([
                molecular_weight > 500,
                logp > 5,
                num_h_donors > 5,
                num_h_acceptors > 10,
            ]),
        }
        print(json.dumps(result))
        """
    )
    args = {"smiles_string": validated.smiles_string}
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_accelerated_stability_of_pharmaceutical_formulations
# ---------------------------------------------------------------------------


class StorageCondition(BaseModel):
    temperature_C: float
    label: Optional[str] = None


class Formulation(BaseModel):
    name: str
    percent_remaining: List[List[float]] = Field(min_length=1)


class AnalyzeAcceleratedStabilityArgs(BaseModel):
    formulations: List[Formulation] = Field(min_length=1)
    storage_conditions: List[StorageCondition] = Field(min_length=2)
    time_points: List[float] = Field(min_length=2)

    @model_validator(mode="after")
    def _shapes_are_consistent(self) -> "AnalyzeAcceleratedStabilityArgs":
        n_conditions = len(self.storage_conditions)
        n_time_points = len(self.time_points)
        for formulation in self.formulations:
            if len(formulation.percent_remaining) != n_conditions:
                raise ValueError(
                    f"formulation {formulation.name!r}: percent_remaining must have one "
                    f"series per storage condition ({n_conditions})"
                )
            for series in formulation.percent_remaining:
                if len(series) != n_time_points:
                    raise ValueError(
                        f"formulation {formulation.name!r}: each percent_remaining series "
                        f"must have one value per time point ({n_time_points})"
                    )
        return self


def analyze_accelerated_stability_of_pharmaceutical_formulations(arguments: dict, driver) -> dict:
    """Real Arrhenius-equation-based accelerated stability analysis. For each
    formulation, fits a first-order degradation rate constant `k` at every
    storage condition (`ln(C/C0) = -k*t` via `scipy.stats.linregress`), then
    fits the Arrhenius equation (`ln(k) = ln(A) - Ea/(R*T)`) across
    conditions' temperatures to get the activation energy, extrapolates `k`
    at 25 C, and predicts a t90 (time to 90% potency) shelf life."""
    validated = AnalyzeAcceleratedStabilityArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json
        import numpy as np
        from scipy.stats import linregress

        formulations = _args["formulations"]
        storage_conditions = _args["storage_conditions"]
        time_points = np.asarray(_args["time_points"], dtype=float)

        R_GAS_CONSTANT = 8.314  # J / (mol * K)
        REFERENCE_TEMP_C = 25.0
        temps_k = np.array([c["temperature_C"] + 273.15 for c in storage_conditions])

        formulation_results = []
        for formulation in formulations:
            rate_constants = []
            for series in formulation["percent_remaining"]:
                series = np.asarray(series, dtype=float)
                c0 = series[0] if series[0] > 0 else 100.0
                ln_ratio = np.log(series / c0)
                slope, intercept, r_value, p_value, std_err = linregress(time_points, ln_ratio)
                rate_constants.append(-float(slope))

            inv_t = 1.0 / temps_k
            ln_k = np.log(np.clip(rate_constants, 1e-12, None))
            slope, intercept, r_value, p_value, std_err = linregress(inv_t, ln_k)
            activation_energy_j_per_mol = -slope * R_GAS_CONSTANT
            ln_a = intercept

            ref_temp_k = REFERENCE_TEMP_C + 273.15
            k_ref = float(np.exp(ln_a - activation_energy_j_per_mol / (R_GAS_CONSTANT * ref_temp_k)))
            t90_days = float(np.log(1 / 0.9) / k_ref) if k_ref > 0 else None

            formulation_results.append({
                "formulation": formulation["name"],
                "rate_constants_per_condition": rate_constants,
                "activation_energy_kJ_per_mol": activation_energy_j_per_mol / 1000.0,
                "arrhenius_ln_A": float(ln_a),
                "arrhenius_fit_r_squared": float(r_value ** 2),
                "predicted_rate_constant_at_25C": k_ref,
                "predicted_shelf_life_t90_days": t90_days,
            })

        result = {
            "reference_temperature_C": REFERENCE_TEMP_C,
            "storage_conditions": storage_conditions,
            "time_points": time_points.tolist(),
            "formulation_results": formulation_results,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "formulations": [f.model_dump() for f in validated.formulations],
        "storage_conditions": [c.model_dump() for c in validated.storage_conditions],
        "time_points": validated.time_points,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# run_3d_chondrogenic_aggregate_assay
# ---------------------------------------------------------------------------


class Run3dChondrogenicAggregateAssayArgs(BaseModel):
    chondrocyte_cells: Dict[str, Any]
    test_compounds: List[Any] = Field(min_length=1)
    culture_duration_days: int = Field(default=21, gt=0)
    measurement_intervals: int = Field(default=7, gt=0)


def run_3d_chondrogenic_aggregate_assay(arguments: dict, driver) -> dict:
    """Protocol generator: builds a structured 3D chondrogenic pellet/
    aggregate culture protocol (chondrocyte pelleting, serum-free
    chondrogenic induction medium, staged compound exposure, and interval
    biochemical/histological readouts) parameterized by the supplied cell
    source, compounds, culture duration, and measurement cadence. This is
    wet-lab guidance text, not a simulated numeric assay result -- still
    routed through the sandbox for the same defense-in-depth reason every
    other tool in this module is (see `_sandbox_tool_base.py`)."""
    validated = Run3dChondrogenicAggregateAssayArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json

        chondrocyte_cells = _args["chondrocyte_cells"]
        test_compounds = _args["test_compounds"]
        culture_duration_days = int(_args["culture_duration_days"])
        measurement_intervals = int(_args["measurement_intervals"])

        measurement_days = list(range(
            measurement_intervals, culture_duration_days + 1, measurement_intervals
        ))
        if not measurement_days or measurement_days[-1] != culture_duration_days:
            measurement_days.append(culture_duration_days)

        cell_type = chondrocyte_cells.get("cell_type", "chondrocytes")
        cell_count = chondrocyte_cells.get("cell_count", "2.5e5")
        compounds_str = ", ".join(str(c) for c in test_compounds)

        protocol_steps = [
            {
                "step": 1, "title": "Cell aggregate formation",
                "description": (
                    f"Pellet {cell_count} {cell_type} per well by centrifugation "
                    "(200-500 x g, 5 min) in a 15 mL conical tube or V-bottom 96-well "
                    "plate to form a compact 3D aggregate."
                ),
            },
            {
                "step": 2, "title": "Chondrogenic induction medium",
                "description": (
                    "Culture in serum-free chondrogenic medium (high-glucose DMEM, "
                    "ITS+ premix, dexamethasone 100 nM, ascorbate-2-phosphate 50 ug/mL, "
                    "sodium pyruvate 1 mM, proline 40 ug/mL, TGF-beta3 10 ng/mL)."
                ),
            },
            {
                "step": 3, "title": "Compound exposure",
                "description": (
                    f"Dose aggregates with test compounds: {compounds_str}; refresh "
                    "medium (and compound) every 2-3 days."
                ),
            },
            {
                "step": 4, "title": "Interval measurements",
                "description": (
                    f"Harvest sentinel aggregates for readout on days {measurement_days} "
                    "(aggregate diameter/wet weight, GAG content via DMMB assay, "
                    "histology - Safranin O/Alcian blue, and COL2A1/ACAN/SOX9 qPCR)."
                ),
            },
            {
                "step": 5, "title": "Endpoint harvest",
                "description": (
                    f"Terminal harvest at day {culture_duration_days} for full "
                    "histological and biochemical characterization."
                ),
            },
        ]

        result = {
            "chondrocyte_cells": chondrocyte_cells,
            "test_compounds": test_compounds,
            "culture_duration_days": culture_duration_days,
            "measurement_intervals": measurement_intervals,
            "measurement_days": measurement_days,
            "protocol_steps": protocol_steps,
            "disclaimer": (
                "Generated wet-lab protocol guidance based on standard 3D chondrogenic "
                "pellet/aggregate culture methodology -- not a simulated numeric assay "
                "result."
            ),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "chondrocyte_cells": validated.chondrocyte_cells,
        "test_compounds": validated.test_compounds,
        "culture_duration_days": validated.culture_duration_days,
        "measurement_intervals": validated.measurement_intervals,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# grade_adverse_events_using_vcog_ctcae
# ---------------------------------------------------------------------------

# Small, illustrative, bundled reference subset of VCOG-CTCAE v2 (Veterinary
# Cooperative Oncology Group - Common Terminology Criteria for Adverse
# Events) hematologic/GI grading thresholds -- NOT the complete official
# table (which spans hundreds of adverse-event terms across every organ
# system). An `event` not covered here is reported as ungraded, never
# assigned a fabricated grade. Bins are `[min, max)`, `None` meaning
# unbounded, ordered worst-to-best; grade 0 means "within normal limits".
_VCOG_CTCAE_GRADING_TABLE: Dict[str, Dict[str, Any]] = {
    "neutropenia": {
        "unit": "cells/uL", "direction": "low_is_worse",
        "grades": [
            {"grade": 4, "min": None, "max": 500.0},
            {"grade": 3, "min": 500.0, "max": 1000.0},
            {"grade": 2, "min": 1000.0, "max": 1500.0},
            {"grade": 1, "min": 1500.0, "max": 2000.0},
            {"grade": 0, "min": 2000.0, "max": None},
        ],
    },
    "anemia": {
        "unit": "g/dL", "direction": "low_is_worse",
        "grades": [
            {"grade": 4, "min": None, "max": 5.0},
            {"grade": 3, "min": 5.0, "max": 7.0},
            {"grade": 2, "min": 7.0, "max": 10.0},
            {"grade": 1, "min": 10.0, "max": 12.0},
            {"grade": 0, "min": 12.0, "max": None},
        ],
    },
    "thrombocytopenia": {
        "unit": "x10^3/uL", "direction": "low_is_worse",
        "grades": [
            {"grade": 4, "min": None, "max": 25.0},
            {"grade": 3, "min": 25.0, "max": 50.0},
            {"grade": 2, "min": 50.0, "max": 100.0},
            {"grade": 1, "min": 100.0, "max": 150.0},
            {"grade": 0, "min": 150.0, "max": None},
        ],
    },
    "diarrhea": {
        "unit": "stools/day above baseline", "direction": "high_is_worse",
        "grades": [
            {"grade": 0, "min": None, "max": 1.0},
            {"grade": 1, "min": 1.0, "max": 3.0},
            {"grade": 2, "min": 3.0, "max": 7.0},
            {"grade": 3, "min": 7.0, "max": 11.0},
            {"grade": 4, "min": 11.0, "max": None},
        ],
    },
    "vomiting": {
        "unit": "episodes/24h", "direction": "high_is_worse",
        "grades": [
            {"grade": 0, "min": None, "max": 1.0},
            {"grade": 1, "min": 1.0, "max": 3.0},
            {"grade": 2, "min": 3.0, "max": 6.0},
            {"grade": 3, "min": 6.0, "max": 11.0},
            {"grade": 4, "min": 11.0, "max": None},
        ],
    },
}


class GradeAdverseEventsUsingVcogCtcaeArgs(BaseModel):
    clinical_data_file: str


def grade_adverse_events_using_vcog_ctcae(arguments: dict, driver) -> dict:
    """Rule-table lookup: reads `clinical_data_file` (a CSV with
    `patient_id,event,value` columns) and grades each row's `value` against
    `_VCOG_CTCAE_GRADING_TABLE`'s illustrative subset of published VCOG-CTCAE
    v2 thresholds. Rows for an unrecognized `event` (or a non-numeric
    `value`) are reported as ungraded with a reason, never assigned a
    fabricated grade."""
    validated = GradeAdverseEventsUsingVcogCtcaeArgs.model_validate(arguments or {})
    clinical_data_file = ensure_safe_relative_path(validated.clinical_data_file)

    script_body = _dedent(
        """
        import csv
        import json

        clinical_data_file = _args["clinical_data_file"]
        grading_table = _args["grading_table"]

        def grade_value(event, value):
            rules = grading_table.get(event.strip().lower())
            if rules is None:
                return None, f"No VCOG-CTCAE grading rule bundled for event {event!r}"
            for bin_ in rules["grades"]:
                lo, hi = bin_["min"], bin_["max"]
                if (lo is None or value >= lo) and (hi is None or value < hi):
                    return bin_["grade"], None
            return None, f"Value {value} for {event!r} did not match any grading bin"

        graded_events = []
        ungraded_events = []
        with open(clinical_data_file, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                event = row.get("event", "")
                raw_value = row.get("value")
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    ungraded_events.append({"row": row, "reason": "value is not numeric"})
                    continue
                grade, reason = grade_value(event, value)
                if grade is None:
                    ungraded_events.append({"row": row, "reason": reason})
                else:
                    graded_events.append({
                        "patient_id": row.get("patient_id"),
                        "event": event,
                        "value": value,
                        "vcog_ctcae_grade": grade,
                    })

        result = {
            "clinical_data_file": clinical_data_file,
            "graded_events": graded_events,
            "ungraded_events": ungraded_events,
            "num_graded": len(graded_events),
            "num_ungraded": len(ungraded_events),
        }
        print(json.dumps(result))
        """
    )
    args = {"clinical_data_file": clinical_data_file, "grading_table": _VCOG_CTCAE_GRADING_TABLE}
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_radiolabeled_antibody_biodistribution
# ---------------------------------------------------------------------------


class AnalyzeRadiolabeledAntibodyBiodistributionArgs(BaseModel):
    time_points: List[float] = Field(min_length=2)
    tissue_data: Dict[str, List[float]] = Field(min_length=1)

    @model_validator(mode="after")
    def _tumor_key_and_matching_lengths(self) -> "AnalyzeRadiolabeledAntibodyBiodistributionArgs":
        if "tumor" not in self.tissue_data:
            raise ValueError("tissue_data must include a 'tumor' key")
        n = len(self.time_points)
        for tissue, values in self.tissue_data.items():
            if len(values) != n:
                raise ValueError(
                    f"tissue_data[{tissue!r}] length ({len(values)}) must match "
                    f"time_points length ({n})"
                )
        return self


def analyze_radiolabeled_antibody_biodistribution(arguments: dict, driver) -> dict:
    """Real per-tissue pharmacokinetic profile fit: for each tissue's
    time-activity series, computes Cmax/Tmax/AUC (trapezoidal rule) and fits
    a biexponential distribution/clearance model
    (`a*exp(-alpha*t) + b*exp(-beta*t)`) via `scipy.optimize.curve_fit`,
    reporting the dominant clearance half-life and tumor-to-normal-tissue AUC
    ratios (`tissue_data` must include a `tumor` key)."""
    validated = AnalyzeRadiolabeledAntibodyBiodistributionArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json
        import numpy as np
        from scipy.integrate import trapezoid
        from scipy.optimize import curve_fit

        time_points = np.asarray(_args["time_points"], dtype=float)
        tissue_data = _args["tissue_data"]

        def biexponential(t, a, alpha, b, beta):
            return a * np.exp(-alpha * t) + b * np.exp(-beta * t)

        def fit_tissue(t, raw_values):
            values = np.asarray(raw_values, dtype=float)
            cmax = float(values.max())
            tmax = float(t[int(values.argmax())])
            auc = float(trapezoid(values, t))
            fit_result = {"cmax": cmax, "tmax": tmax, "auc": auc}
            try:
                p0 = [max(values[0] / 2, 1.0), 0.1, max(values[0] / 2, 1.0), 0.01]
                popt, _ = curve_fit(biexponential, t, values, p0=p0, maxfev=10000)
                a, alpha, b, beta = (float(x) for x in popt)
                slow_rate = min(alpha, beta) if min(alpha, beta) > 0 else max(alpha, beta)
                half_life = float(np.log(2) / slow_rate) if slow_rate > 0 else None
                fit_result.update({
                    "model": "biexponential", "a": a, "alpha": alpha, "b": b, "beta": beta,
                    "clearance_half_life_hr": half_life,
                })
            except Exception as exc:
                fit_result.update({"model": "fit_failed", "fit_error": str(exc)})
            return fit_result

        per_tissue = {name: fit_tissue(time_points, values) for name, values in tissue_data.items()}
        tumor_auc = per_tissue["tumor"]["auc"]
        tumor_to_tissue_auc_ratios = {
            name: (tumor_auc / stats["auc"]) if stats.get("auc") else None
            for name, stats in per_tissue.items() if name != "tumor"
        }

        result = {
            "time_points": time_points.tolist(),
            "per_tissue_pharmacokinetics": per_tissue,
            "tumor_to_tissue_auc_ratios": tumor_to_tissue_auc_ratios,
        }
        print(json.dumps(result))
        """
    )
    args = {"time_points": validated.time_points, "tissue_data": validated.tissue_data}
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# estimate_alpha_particle_radiotherapy_dosimetry
# ---------------------------------------------------------------------------


class _TissueBiodistributionEntry(BaseModel):
    time_hr: List[float] = Field(min_length=1)
    activity_MBq: List[float] = Field(min_length=1)
    mass_g: float = Field(gt=0)

    @model_validator(mode="after")
    def _matching_lengths(self) -> "_TissueBiodistributionEntry":
        if len(self.time_hr) != len(self.activity_MBq):
            raise ValueError("time_hr and activity_MBq must be the same length")
        return self


class EstimateAlphaParticleRadiotherapyDosimetryArgs(BaseModel):
    biodistribution_data: Dict[str, _TissueBiodistributionEntry] = Field(min_length=1)
    radiation_parameters: Dict[str, Any]
    output_file: str = "dosimetry_results.csv"

    @field_validator("radiation_parameters")
    @classmethod
    def _requires_energy_per_decay(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not any(k.lower() == "energy_per_decay_mev" for k in value):
            raise ValueError(
                "radiation_parameters must include an 'energy_per_decay_MeV' entry "
                "(mean alpha-particle energy released per decay, in MeV)"
            )
        return value


def estimate_alpha_particle_radiotherapy_dosimetry(arguments: dict, driver) -> dict:
    """Real closed-form MIRD-schema (Medical Internal Radiation Dose)
    absorbed-dose calculation: `D = Delta * A~ * phi / m`, where `Delta` is
    the mean energy emitted per decay (`energy_per_decay_MeV *
    joules_per_MeV`), `A~` is the cumulated (time-integrated) activity per
    tissue (trapezoidal AUC of the activity-time curve), `phi` is the
    absorbed fraction (defaults to 1.0 -- local/self-dose deposition, the
    standard simplifying assumption for short-range alpha particles), and
    `m` is the tissue mass."""
    validated = EstimateAlphaParticleRadiotherapyDosimetryArgs.model_validate(arguments or {})
    output_file = ensure_safe_relative_path(validated.output_file)

    energy_key = next(
        k for k in validated.radiation_parameters if k.lower() == "energy_per_decay_mev"
    )
    radiation_parameters = dict(validated.radiation_parameters)
    radiation_parameters["energy_per_decay_mev"] = radiation_parameters.pop(energy_key)

    script_body = _dedent(
        """
        import json
        import numpy as np
        from scipy.integrate import trapezoid

        biodistribution_data = _args["biodistribution_data"]
        radiation_parameters = _args["radiation_parameters"]
        output_file = _args["output_file"]

        energy_per_decay_mev = float(radiation_parameters["energy_per_decay_mev"])
        absorbed_fraction = float(radiation_parameters.get("absorbed_fraction", 1.0))
        joules_per_mev = 1.602176634e-13

        per_tissue = {}
        for tissue, data in biodistribution_data.items():
            time_hr = np.asarray(data["time_hr"], dtype=float)
            activity_mbq = np.asarray(data["activity_MBq"], dtype=float)
            mass_kg = float(data["mass_g"]) / 1000.0

            cumulated_activity_mbq_h = float(trapezoid(activity_mbq, time_hr))
            cumulated_activity_bq_s = cumulated_activity_mbq_h * 1e6 * 3600.0
            absorbed_dose_gy = (
                joules_per_mev * energy_per_decay_mev * cumulated_activity_bq_s * absorbed_fraction
            ) / mass_kg

            per_tissue[tissue] = {
                "cumulated_activity_MBq_h": cumulated_activity_mbq_h,
                "mass_g": float(data["mass_g"]),
                "absorbed_dose_Gy": absorbed_dose_gy,
            }

        with open(output_file, "w") as fh:
            fh.write("tissue,cumulated_activity_MBq_h,mass_g,absorbed_dose_Gy\\n")
            for tissue, stats in per_tissue.items():
                fh.write(
                    f"{tissue},{stats['cumulated_activity_MBq_h']:.6f},"
                    f"{stats['mass_g']:.6f},{stats['absorbed_dose_Gy']:.6f}\\n"
                )

        result = {
            "output_file": output_file,
            "energy_per_decay_MeV": energy_per_decay_mev,
            "absorbed_fraction": absorbed_fraction,
            "per_tissue_dosimetry": per_tissue,
            "mird_schema_note": (
                "MIRD schema: D = Delta * A_tilde * phi / m -- Delta = mean energy "
                "emitted per decay, A_tilde = cumulated (time-integrated) activity, "
                "phi = absorbed fraction (defaulted to 1.0, i.e. local/self-dose "
                "deposition, appropriate for short-range alpha particles), m = target "
                "tissue mass."
            ),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "biodistribution_data": {
            name: entry.model_dump() for name, entry in validated.biodistribution_data.items()
        },
        "radiation_parameters": radiation_parameters,
        "output_file": output_file,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# perform_mwas_cyp2c19_metabolizer_status
# ---------------------------------------------------------------------------


class PerformMwasCyp2c19MetabolizerStatusArgs(BaseModel):
    methylation_data_path: str
    metabolizer_status_path: str
    covariates_path: Optional[str] = None
    pvalue_threshold: float = Field(default=0.05, gt=0, le=1.0)
    output_file: str = "significant_cpg_sites.csv"


def perform_mwas_cyp2c19_metabolizer_status(arguments: dict, driver) -> dict:
    """Real per-CpG-site methylome-wide association regression: for every
    CpG column in `methylation_data_path`, fits an OLS model (`statsmodels`)
    of methylation beta value on CYP2C19 metabolizer status (plus any
    `covariates_path` columns), applies Benjamini-Hochberg FDR correction
    across all tested sites, and reports sites with `p_value <
    pvalue_threshold`."""
    validated = PerformMwasCyp2c19MetabolizerStatusArgs.model_validate(arguments or {})
    methylation_data_path = ensure_safe_relative_path(validated.methylation_data_path)
    metabolizer_status_path = ensure_safe_relative_path(validated.metabolizer_status_path)
    covariates_path = (
        ensure_safe_relative_path(validated.covariates_path) if validated.covariates_path else None
    )
    output_file = ensure_safe_relative_path(validated.output_file)

    script_body = _dedent(
        """
        import json
        import pandas as pd
        import statsmodels.api as sm
        from statsmodels.stats.multitest import multipletests

        methylation_data_path = _args["methylation_data_path"]
        metabolizer_status_path = _args["metabolizer_status_path"]
        covariates_path = _args.get("covariates_path")
        pvalue_threshold = float(_args["pvalue_threshold"])
        output_file = _args["output_file"]

        methylation_df = pd.read_csv(methylation_data_path, index_col=0)
        status_df = pd.read_csv(metabolizer_status_path, index_col=0)
        status_col = status_df.columns[0]

        sample_index = methylation_df.index.intersection(status_df.index)
        if len(sample_index) == 0:
            raise ValueError(
                "No overlapping sample IDs between methylation_data_path and "
                "metabolizer_status_path"
            )

        design = pd.DataFrame(index=sample_index)
        design["metabolizer_status"] = pd.to_numeric(
            status_df.loc[sample_index, status_col], errors="coerce"
        )

        if covariates_path:
            covariates_df = pd.read_csv(covariates_path, index_col=0)
            sample_index = sample_index.intersection(covariates_df.index)
            design = design.loc[sample_index]
            for col in covariates_df.columns:
                design[col] = pd.to_numeric(covariates_df.loc[sample_index, col], errors="coerce")

        design = sm.add_constant(design.dropna())
        methylation_df = methylation_df.loc[design.index]

        tested = []
        for cpg in methylation_df.columns:
            y = pd.to_numeric(methylation_df[cpg], errors="coerce")
            valid = y.notna()
            if valid.sum() < design.shape[1] + 2:
                continue
            model = sm.OLS(y[valid], design.loc[valid]).fit()
            if "metabolizer_status" not in model.params.index:
                continue
            tested.append({
                "cpg_site": cpg,
                "coefficient": float(model.params["metabolizer_status"]),
                "p_value": float(model.pvalues["metabolizer_status"]),
                "n_samples": int(valid.sum()),
            })

        if tested:
            _, qvals, _, _ = multipletests([r["p_value"] for r in tested], method="fdr_bh")
            for row, qval in zip(tested, qvals):
                row["q_value"] = float(qval)

        significant = sorted(
            (r for r in tested if r["p_value"] < pvalue_threshold), key=lambda r: r["p_value"],
        )
        pd.DataFrame(significant).to_csv(output_file, index=False)

        result = {
            "output_file": output_file,
            "n_cpg_sites_tested": len(tested),
            "n_significant": len(significant),
            "pvalue_threshold": pvalue_threshold,
            "significant_cpg_sites": significant,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "methylation_data_path": methylation_data_path,
        "metabolizer_status_path": metabolizer_status_path,
        "covariates_path": covariates_path,
        "pvalue_threshold": validated.pvalue_threshold,
        "output_file": output_file,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_xenograft_tumor_growth_inhibition
# ---------------------------------------------------------------------------


class AnalyzeXenograftTumorGrowthInhibitionArgs(BaseModel):
    data_path: str
    time_column: str
    volume_column: str
    group_column: str
    subject_column: str
    output_dir: str = "./results"


def analyze_xenograft_tumor_growth_inhibition(arguments: dict, driver) -> dict:
    """Real tumor growth inhibition (TGI) statistics: fits each subject's
    exponential growth rate (`ln(V) = ln(V0) + k*t` via
    `scipy.stats.linregress`), groups by `group_column`, treats the group
    with the highest mean growth rate as the untreated/control reference
    (the standard assumption -- untreated tumors grow fastest), computes
    each other group's TGI% relative to it, and compares groups' growth
    rates with a Welch t-test (2 groups) or one-way ANOVA (>2 groups)."""
    validated = AnalyzeXenograftTumorGrowthInhibitionArgs.model_validate(arguments or {})
    data_path = ensure_safe_relative_path(validated.data_path)
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os

        import numpy as np
        import pandas as pd
        from scipy import stats

        data_path = _args["data_path"]
        time_column = _args["time_column"]
        volume_column = _args["volume_column"]
        group_column = _args["group_column"]
        subject_column = _args["subject_column"]
        output_dir = _args["output_dir"]

        os.makedirs(output_dir, exist_ok=True)

        df = pd.read_csv(data_path)
        required_columns = (time_column, volume_column, group_column, subject_column)
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Column {col!r} not found in data_path")
        df = df[list(required_columns)].dropna()
        df[time_column] = pd.to_numeric(df[time_column])
        df[volume_column] = pd.to_numeric(df[volume_column])

        growth_rates = []
        for (subject, group), sub_df in df.groupby([subject_column, group_column]):
            sub_df = sub_df.sort_values(time_column)
            if len(sub_df) < 2 or (sub_df[volume_column] <= 0).any():
                continue
            slope, intercept, r_value, p_value, std_err = stats.linregress(
                sub_df[time_column], np.log(sub_df[volume_column])
            )
            growth_rates.append({
                "subject": subject, "group": group, "growth_rate_k": float(slope),
                "r_squared": float(r_value ** 2),
                "baseline_volume": float(sub_df[volume_column].iloc[0]),
                "final_volume": float(sub_df[volume_column].iloc[-1]),
            })

        growth_df = pd.DataFrame(growth_rates)
        if growth_df.empty:
            raise ValueError(
                "No subject had >=2 valid, positive-volume timepoints to fit a growth rate"
            )

        group_summary = growth_df.groupby("group").agg(
            mean_growth_rate=("growth_rate_k", "mean"),
            mean_baseline_volume=("baseline_volume", "mean"),
            mean_final_volume=("final_volume", "mean"),
            n=("subject", "count"),
        ).reset_index()

        control_group = group_summary.loc[group_summary["mean_growth_rate"].idxmax(), "group"]
        control_row = group_summary[group_summary["group"] == control_group].iloc[0]
        control_delta = control_row["mean_final_volume"] - control_row["mean_baseline_volume"]

        tgi_results = []
        for _, row in group_summary.iterrows():
            if row["group"] == control_group:
                tgi_percent = 0.0
            else:
                treatment_delta = row["mean_final_volume"] - row["mean_baseline_volume"]
                tgi_percent = (
                    float((1 - (treatment_delta / control_delta)) * 100)
                    if control_delta != 0 else None
                )
            tgi_results.append({"group": row["group"], "tgi_percent": tgi_percent})

        groups = growth_df["group"].unique().tolist()
        if len(groups) == 2:
            a = growth_df[growth_df["group"] == groups[0]]["growth_rate_k"]
            b = growth_df[growth_df["group"] == groups[1]]["growth_rate_k"]
            stat, pvalue = stats.ttest_ind(a, b, equal_var=False)
            test_used = "welch_t_test"
        elif len(groups) > 2:
            samples = [growth_df[growth_df["group"] == g]["growth_rate_k"] for g in groups]
            stat, pvalue = stats.f_oneway(*samples)
            test_used = "one_way_anova"
        else:
            stat, pvalue, test_used = None, None, "insufficient_groups"

        output_summary_csv = os.path.join(output_dir, "tumor_growth_inhibition_summary.csv")
        group_summary.to_csv(output_summary_csv, index=False)

        result = {
            "output_dir": output_dir,
            "output_summary_csv": output_summary_csv,
            "control_group_assumption": (
                f"{control_group!r} selected as the reference/control group because it "
                "has the highest mean per-subject exponential growth rate among the "
                "supplied groups (standard assumption: untreated tumors grow fastest)."
            ),
            "group_summary": group_summary.to_dict(orient="records"),
            "tumor_growth_inhibition_percent": tgi_results,
            "growth_rate_group_comparison_test": test_used,
            "test_statistic": float(stat) if stat is not None else None,
            "p_value": float(pvalue) if pvalue is not None else None,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "data_path": data_path,
        "time_column": validated.time_column,
        "volume_column": validated.volume_column,
        "group_column": validated.group_column,
        "subject_column": validated.subject_column,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_western_blot
# ---------------------------------------------------------------------------


class AnalyzeWesternBlotArgs(BaseModel):
    blot_image_path: str
    target_bands: List[Dict[str, Any]] = Field(min_length=1)
    loading_control_band: Dict[str, Any]
    antibody_info: Dict[str, Any] = Field(default_factory=dict)
    output_dir: str = "./results"

    @field_validator("target_bands")
    @classmethod
    def _bands_have_position(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for band in value:
            if len(band.get("position") or []) != 4:
                raise ValueError(
                    "each target band must include a 4-element 'position' bounding box "
                    "[x1, y1, x2, y2]"
                )
        return value

    @field_validator("loading_control_band")
    @classmethod
    def _control_has_position(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if len(value.get("position") or []) != 4:
            raise ValueError(
                "loading_control_band must include a 4-element 'position' bounding box "
                "[x1, y1, x2, y2]"
            )
        return value


def analyze_western_blot(arguments: dict, driver) -> dict:
    """Tier C -- general-purpose scikit-image densitometric Western blot
    quantification, NOT clinically or publication-validated blot-
    quantification software. For each user-supplied band bounding box,
    integrates background-subtracted pixel intensity (image inverted so band
    signal is high-intensity, local background estimated from a thin margin
    around the box) and normalizes every target band to
    `loading_control_band`'s intensity."""
    validated = AnalyzeWesternBlotArgs.model_validate(arguments or {})
    blot_image_path = ensure_safe_relative_path(validated.blot_image_path)
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os

        import numpy as np
        from skimage import color, io

        blot_image_path = _args["blot_image_path"]
        target_bands = _args["target_bands"]
        loading_control_band = _args["loading_control_band"]
        antibody_info = _args["antibody_info"]
        output_dir = _args["output_dir"]

        os.makedirs(output_dir, exist_ok=True)

        image = io.imread(blot_image_path)
        if image.ndim == 3:
            image = color.rgb2gray(image)
        image = image.astype(float)
        inverted = image.max() - image  # dark bands on a light background -> high signal

        def band_intensity(band, img):
            x1, y1, x2, y2 = band["position"]
            x1, x2 = sorted((int(x1), int(x2)))
            y1, y2 = sorted((int(y1), int(y2)))
            roi = img[y1:y2, x1:x2]
            if roi.size == 0:
                raise ValueError(f"Band {band.get('name', '?')!r} has an empty bounding box")
            pad = 5
            y1b, y2b = max(y1 - pad, 0), min(y2 + pad, img.shape[0])
            x1b, x2b = max(x1 - pad, 0), min(x2 + pad, img.shape[1])
            border = img[y1b:y2b, x1b:x2b]
            background = float(np.median(border)) if border.size else 0.0
            return float(max(float(np.sum(roi)) - background * roi.size, 0.0))

        control_intensity = band_intensity(loading_control_band, inverted)
        if control_intensity <= 0:
            raise ValueError(
                "Loading control band has zero or negative net intensity; cannot normalize"
            )

        target_band_results = []
        for band in target_bands:
            intensity = band_intensity(band, inverted)
            target_band_results.append({
                "name": band.get("name"),
                "expected_kda": band.get("expected_kda"),
                "raw_integrated_intensity": intensity,
                "normalized_to_loading_control": intensity / control_intensity,
            })

        result = {
            "blot_image_path": blot_image_path,
            "antibody_info": antibody_info,
            "loading_control_band": loading_control_band,
            "loading_control_intensity": control_intensity,
            "target_bands": target_band_results,
            "method_disclaimer": (
                "General-purpose densitometric quantification (background-subtracted "
                "pixel-intensity integration within user-supplied bounding boxes, "
                "normalized to a loading-control band) via scikit-image -- a general "
                "image-processing method, NOT clinically or publication-validated blot "
                "quantification software."
            ),
        }
        with open(os.path.join(output_dir, "western_blot_quantification.json"), "w") as fh:
            json.dump(result, fh)
        print(json.dumps(result))
        """
    )
    args = {
        "blot_image_path": blot_image_path,
        "target_bands": validated.target_bands,
        "loading_control_band": validated.loading_control_band,
        "antibody_info": validated.antibody_info,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# predict_admet_properties (network-access exception, see module docstring)
# ---------------------------------------------------------------------------

_VALID_ADMET_MODEL_TYPES = {
    "MPNN", "CNN", "Morgan", "Pubchem", "Daylight", "rdkit_2d_normalized",
}

# Small curated subset of TDC's `ADMET_Group` benchmark spanning distinct
# ADMET categories, chosen for having comparatively small training splits so
# a from-scratch, few-epoch fit stays tractable inside the sandbox's CPU
# budget -- NOT the full ~22-endpoint ADMET_Group suite.
_ADMET_ENDPOINTS = [
    {"name": "Caco2_Wang", "category": "absorption"},
    {"name": "BBB_Martins", "category": "distribution"},
    {"name": "hERG", "category": "toxicity"},
]


class PredictAdmetPropertiesArgs(BaseModel):
    smiles_list: List[str] = Field(min_length=1)
    ADMET_model_type: str = "MPNN"

    @field_validator("smiles_list")
    @classmethod
    def _non_empty_smiles(cls, value: List[str]) -> List[str]:
        cleaned = [s.strip() for s in value]
        if any(not s for s in cleaned):
            raise ValueError("smiles_list must not contain empty strings")
        return cleaned

    @field_validator("ADMET_model_type")
    @classmethod
    def _valid_model_type(cls, value: str) -> str:
        if value not in _VALID_ADMET_MODEL_TYPES:
            raise ValueError(f"ADMET_model_type must be one of {sorted(_VALID_ADMET_MODEL_TYPES)}")
        return value


def predict_admet_properties(arguments: dict, driver) -> dict:
    """Real DeepPurpose `CompoundPred` ADMET prediction -- but see the module
    docstring's network-access note first: DeepPurpose does NOT ship a single
    bundled/downloadable "ADMET checkpoint"; its own documented ADMET
    workflow is to train a small `CompoundPred` model per endpoint on real
    TDC `ADMET_Group` benchmark data. This handler does exactly that for a
    small curated subset of endpoints (`_ADMET_ENDPOINTS`, one lightweight
    (`train_epoch=3`) fit per endpoint per call) and predicts on
    `smiles_list`. This means real outbound network access (to fetch TDC's
    benchmark data) and non-trivial CPU time are required on EVERY call, not
    just a one-time "first call" -- this sandbox has no writable, persistent
    location to cache a trained model across separate invocations. Runs
    against a driver with `allow_network=True` (see
    `_network_enabled_driver`), never the shared, network-isolated driver
    every other tool in this module uses."""
    validated = PredictAdmetPropertiesArgs.model_validate(arguments or {})
    network_driver = _network_enabled_driver(driver)

    script_body = _dedent(
        """
        import json

        from DeepPurpose import CompoundPred as models
        from DeepPurpose.utils import data_process, generate_config
        from tdc import BenchmarkGroup

        smiles_list = _args["smiles_list"]
        drug_encoding = _args["admet_model_type"]
        admet_endpoints = _args["admet_endpoints"]

        group = BenchmarkGroup(name="ADMET_Group", path="/tmp/tdc_admet_data")

        predictions_per_smiles = {smiles: {} for smiles in smiles_list}
        endpoints_evaluated = []
        for endpoint in admet_endpoints:
            benchmark_name = endpoint["name"]
            benchmark = group.get(benchmark_name)
            train_df, valid_df = group.get_train_valid_split(
                benchmark=benchmark["name"], split_type="default", seed=1,
            )

            train = data_process(
                X_drug=train_df.Drug.values, y=train_df.Y.values,
                drug_encoding=drug_encoding, split_method="no_split",
            )
            val = data_process(
                X_drug=valid_df.Drug.values, y=valid_df.Y.values,
                drug_encoding=drug_encoding, split_method="no_split",
            )
            config = generate_config(
                drug_encoding=drug_encoding, cls_hidden_dims=[128], train_epoch=3,
                LR=0.001, batch_size=64,
            )
            model = models.model_initialize(**config)
            model.train(train, val, val, verbose=False)

            query = data_process(
                X_drug=smiles_list, y=[0.0] * len(smiles_list),
                drug_encoding=drug_encoding, split_method="no_split",
            )
            predictions = model.predict(query)
            for smiles, pred in zip(smiles_list, predictions):
                predictions_per_smiles[smiles][benchmark_name] = float(pred)

            endpoints_evaluated.append({
                "endpoint": benchmark_name, "category": endpoint["category"],
                "n_train": len(train_df), "n_valid": len(valid_df),
            })

        result = {
            "admet_model_type": drug_encoding,
            "endpoints_evaluated": endpoints_evaluated,
            "predictions_per_smiles": predictions_per_smiles,
            "disclaimer": (
                "Each endpoint is a lightweight (train_epoch=3) DeepPurpose CompoundPred "
                "model trained fresh, per call, on the real TDC ADMET_Group benchmark "
                "training split for that endpoint -- not a bundled pretrained checkpoint. "
                "Outbound network access and non-trivial CPU time are required on EVERY "
                "call, not just the first."
            ),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "smiles_list": validated.smiles_list,
        "admet_model_type": validated.ADMET_model_type,
        "admet_endpoints": _ADMET_ENDPOINTS,
    }
    return run_in_sandbox(network_driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# predict_binding_affinity_protein_1d_sequence (network-access exception)
# ---------------------------------------------------------------------------

_VALID_AFFINITY_MODEL_TYPES = {
    "MPNN-CNN", "CNN-CNN", "Morgan-CNN", "Morgan-AAC", "CNN-AAC", "Daylight-CNN",
}


class PredictBindingAffinityProteinSequenceArgs(BaseModel):
    smiles_list: List[str] = Field(min_length=1)
    amino_acid_sequence: str
    affinity_model_type: str = "MPNN-CNN"

    @field_validator("smiles_list")
    @classmethod
    def _non_empty_smiles(cls, value: List[str]) -> List[str]:
        cleaned = [s.strip() for s in value]
        if any(not s for s in cleaned):
            raise ValueError("smiles_list must not contain empty strings")
        return cleaned

    @field_validator("amino_acid_sequence")
    @classmethod
    def _non_empty_sequence(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("amino_acid_sequence must be a non-empty string")
        return value

    @field_validator("affinity_model_type")
    @classmethod
    def _valid_model_type(cls, value: str) -> str:
        if value not in _VALID_AFFINITY_MODEL_TYPES:
            raise ValueError(
                f"affinity_model_type must be one of {sorted(_VALID_AFFINITY_MODEL_TYPES)} "
                "(DrugEncoding-TargetEncoding, matching DeepPurpose's pretrained-model "
                "naming convention)"
            )
        return value


def predict_binding_affinity_protein_1d_sequence(arguments: dict, driver) -> dict:
    """Real DeepPurpose DTI binding-affinity prediction: loads a pretrained
    `models.model_pretrained(model="<DrugEncoding>_<TargetEncoding>_BindingDB")`
    checkpoint (real weights downloaded from DeepPurpose's model zoo the
    first time a given `affinity_model_type` is requested on this
    deployment) and predicts binding affinity (pKd) for each SMILES against
    `amino_acid_sequence`. Runs against a driver with `allow_network=True`
    (see `_network_enabled_driver`), never the shared, network-isolated
    driver every other tool in this module uses."""
    validated = PredictBindingAffinityProteinSequenceArgs.model_validate(arguments or {})
    network_driver = _network_enabled_driver(driver)
    drug_encoding, target_encoding = validated.affinity_model_type.split("-")
    pretrained_model_name = f"{drug_encoding}_{target_encoding}_BindingDB"

    script_body = _dedent(
        """
        import json

        from DeepPurpose import DTI as models
        from DeepPurpose import utils

        smiles_list = _args["smiles_list"]
        amino_acid_sequence = _args["amino_acid_sequence"]
        pretrained_model_name = _args["pretrained_model_name"]

        model = models.model_pretrained(model=pretrained_model_name)
        X_target = [amino_acid_sequence] * len(smiles_list)
        y_placeholder = [0.0] * len(smiles_list)

        X_pred = utils.data_process(
            X_drug=smiles_list, X_target=X_target, y=y_placeholder,
            drug_encoding=model.drug_encoding, target_encoding=model.target_encoding,
            split_method="no_split",
        )
        predictions = model.predict(X_pred)

        result = {
            "affinity_model_type": _args["affinity_model_type"],
            "pretrained_model": pretrained_model_name,
            "amino_acid_sequence_length": len(amino_acid_sequence),
            "predictions": [
                {"smiles": smiles, "predicted_binding_affinity_pKd": float(pred)}
                for smiles, pred in zip(smiles_list, predictions)
            ],
        }
        print(json.dumps(result))
        """
    )
    args = {
        "smiles_list": validated.smiles_list,
        "amino_acid_sequence": validated.amino_acid_sequence,
        "affinity_model_type": validated.affinity_model_type,
        "pretrained_model_name": pretrained_model_name,
    }
    return run_in_sandbox(network_driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# run_diffdock_with_smiles -- Tier D, see backend/docs/tools/UNSUPPORTED.md
# ---------------------------------------------------------------------------


class RunDiffdockWithSmilesArgs(BaseModel):
    pdb_path: str
    smiles_string: str
    local_output_dir: str
    gpu_device: int = 0
    use_gpu: bool = True


def run_diffdock_with_smiles(arguments: dict, driver) -> dict:
    """**Tier D -- unsupported.** DiffDock is a diffusion model for docking
    pose generation that needs its own pretrained checkpoint, a CUDA GPU, and
    its own Docker container per Biomni's own tool description -- none of
    that is available in this project's single-container bwrap-sandbox
    deployment. See `backend/docs/tools/UNSUPPORTED.md`."""
    RunDiffdockWithSmilesArgs.model_validate(arguments or {})
    raise NotSupportedError(
        "run_diffdock_with_smiles requires the DiffDock pretrained diffusion-model "
        "checkpoint, a CUDA GPU, and DiffDock's own Docker container (not runnable "
        "nested inside this project's single-container bwrap sandbox); see "
        "backend/docs/tools/UNSUPPORTED.md."
    )


# ---------------------------------------------------------------------------
# retrieve_topk_repurposing_drugs_from_disease_txgnn -- Tier D
# ---------------------------------------------------------------------------


class RetrieveTopkRepurposingDrugsTxgnnArgs(BaseModel):
    disease_name: str
    k: int = Field(default=5, gt=0)

    @field_validator("disease_name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("disease_name must be a non-empty string")
        return value


def retrieve_topk_repurposing_drugs_from_disease_txgnn(arguments: dict, driver) -> dict:
    """**Tier D -- unsupported.** TxGNN is a trained graph neural network
    over a specific knowledge-graph snapshot; there is no publicly
    redistributable pretrained checkpoint bundled with this deployment, and
    training one from scratch is a research project of its own, not a
    packaging task. See `backend/docs/tools/UNSUPPORTED.md`."""
    RetrieveTopkRepurposingDrugsTxgnnArgs.model_validate(arguments or {})
    raise NotSupportedError(
        "retrieve_topk_repurposing_drugs_from_disease_txgnn requires a trained TxGNN "
        "checkpoint plus the exact knowledge graph it was trained against, neither of "
        "which is bundled with or obtainable by this deployment; see "
        "backend/docs/tools/UNSUPPORTED.md."
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_TOOL_HANDLERS = {
    "docking_autodock_vina": docking_autodock_vina,
    "run_autosite": run_autosite,
    "calculate_physicochemical_properties": calculate_physicochemical_properties,
    "analyze_accelerated_stability_of_pharmaceutical_formulations": (
        analyze_accelerated_stability_of_pharmaceutical_formulations
    ),
    "run_3d_chondrogenic_aggregate_assay": run_3d_chondrogenic_aggregate_assay,
    "grade_adverse_events_using_vcog_ctcae": grade_adverse_events_using_vcog_ctcae,
    "analyze_radiolabeled_antibody_biodistribution": analyze_radiolabeled_antibody_biodistribution,
    "estimate_alpha_particle_radiotherapy_dosimetry": estimate_alpha_particle_radiotherapy_dosimetry,
    "perform_mwas_cyp2c19_metabolizer_status": perform_mwas_cyp2c19_metabolizer_status,
    "analyze_xenograft_tumor_growth_inhibition": analyze_xenograft_tumor_growth_inhibition,
    "analyze_western_blot": analyze_western_blot,
    "predict_admet_properties": predict_admet_properties,
    "predict_binding_affinity_protein_1d_sequence": predict_binding_affinity_protein_1d_sequence,
    "run_diffdock_with_smiles": run_diffdock_with_smiles,
    "retrieve_topk_repurposing_drugs_from_disease_txgnn": (
        retrieve_topk_repurposing_drugs_from_disease_txgnn
    ),
}


def register_pharmacology_tools(registry, driver) -> List[str]:
    """Registers every Drug discovery & pharmacology action tool into
    `registry`, each bound to the shared sandbox `driver`. `predict_admet_
    properties` / `predict_binding_affinity_protein_1d_sequence` internally
    upgrade to a network-enabled driver themselves (see
    `_network_enabled_driver` and the module docstring) -- every other tool
    keeps using `driver` exactly as given, network-isolated. Returns the list
    of registered tool names."""
    for name, handler in _TOOL_HANDLERS.items():
        registry.register_server(name, functools.partial(handler, driver=driver))
    return list(_TOOL_HANDLERS.keys())
