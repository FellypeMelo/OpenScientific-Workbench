"""Biophysics & biochemical assays action tools (Fase 5).

Implements every tool listed under the "Categoria: Biophysics & biochemical
assays" heading of `backend/docs/tools/action_tool_catalog.md`. Every tool in
this category is Tier A or Tier B (no Tier D entries here -- nothing needs a
proprietary pretrained checkpoint or a GPU cluster) and therefore runs its
real scientific logic inside the sandbox via `run_in_sandbox` (see
`_sandbox_tool_base.py`'s module docstring for exactly why -- LLM-influenced
arguments never reach an in-process scipy/biopython/ViennaRNA import in this
trusted backend process).

Per-tool tiering (see `action_tool_catalog.md` for the authoritative source,
this is a recap, not a re-derivation):

- `analyze_circular_dichroism_spectra`: Tier A/B hybrid -- secondary-structure
  fraction from the Chen, Yang & Chau (1974) MRE-222nm empirical formula
  (closed-form, Tier A) plus an optional two-state Boltzmann-sigmoid thermal
  melting-curve fit (`scipy.optimize.curve_fit`, Tier B) when
  `temperature_data`/`thermal_cd_data` are supplied.
- `analyze_rna_secondary_structure_features`: Tier A -- real stack-based
  dot-bracket parsing (base pairs, stems, hairpin loops) plus an optional
  real ViennaRNA `fold_compound.eval_structure` free-energy calculation
  (Turner nearest-neighbor model) when `sequence` is supplied.
- `analyze_protease_kinetics`: Tier B -- per-substrate-concentration initial
  velocity via linear regression (`scipy.stats.linregress`) on the
  fluorogenic time course, then a real Michaelis-Menten fit
  (`scipy.optimize.curve_fit`) of v0 vs [S].
- `analyze_enzyme_kinetics_assay`: Tier B -- per-modulator four-parameter
  logistic (Hill) dose-response fit (`scipy.optimize.curve_fit`) of velocity
  vs modulator concentration, the standard closed-form pharmacology/
  enzymology dose-response model.
- `analyze_itc_binding_thermodynamics`: Tier B -- real single-site Wiseman
  isotherm fit (Wiseman et al., Anal. Biochem. 1989) via
  `scipy.optimize.curve_fit`, deriving n, Ka/Kd, deltaH, deltaG, deltaS.
- `analyze_protein_conservation`: Tier A -- real `mafft` multiple sequence
  alignment (argv-list subprocess call) followed by real per-column identity-
  fraction conservation scoring.
- `analyze_atp_luminescence_assay`: Tier B -- real linear-regression
  (`scipy.stats.linregress`) standard curve (luminescence -> ATP
  concentration) applied to sample data, with optional per-sample
  normalization.
- `analyze_bacterial_growth_curve` / `analyze_bacterial_growth_rate`: Tier B,
  same family (share one script body) -- real fit of the Zwietering et al.
  (1990, Appl. Environ. Microbiol. 56:1875-1881) modified logistic growth
  model via `scipy.optimize.curve_fit`, yielding max growth rate, lag time,
  and doubling time.

Every file-path-shaped argument (`output_dir`, `output_prefix`,
`itc_data_path`, `data_file`, `standard_curve_file`, and a string
`normalization_data` path) is passed through `ensure_safe_relative_path`
before being handed to the sandbox.
"""
import functools
import textwrap
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from src.domain.services.path_guard import ensure_safe_relative_path
from src.infrastructure.tools._sandbox_tool_base import run_in_sandbox


def _dedent(script: str) -> str:
    """Strips this module's Python-source indentation off a `script_body`
    literal so the code that actually reaches the sandbox starts every line
    at column 0 (required -- `run_in_sandbox` concatenates `script_body`
    directly after its own top-level `_args` loading preamble)."""
    return textwrap.dedent(script).strip("\n")


# ---------------------------------------------------------------------------
# analyze_circular_dichroism_spectra
# ---------------------------------------------------------------------------


class AnalyzeCircularDichroismSpectraArgs(BaseModel):
    sample_name: str
    sample_type: str
    wavelength_data: List[float] = Field(min_length=2)
    cd_signal_data: List[float] = Field(min_length=2)
    temperature_data: Optional[List[float]] = None
    thermal_cd_data: Optional[List[float]] = None
    output_dir: str = "./"

    @field_validator("sample_name", "sample_type")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _validate_shapes(self) -> "AnalyzeCircularDichroismSpectraArgs":
        if len(self.wavelength_data) != len(self.cd_signal_data):
            raise ValueError("wavelength_data and cd_signal_data must be the same length")
        if (self.temperature_data is None) != (self.thermal_cd_data is None):
            raise ValueError("temperature_data and thermal_cd_data must be provided together")
        if self.temperature_data is not None and len(self.temperature_data) != len(self.thermal_cd_data):
            raise ValueError("temperature_data and thermal_cd_data must be the same length")
        return self


def analyze_circular_dichroism_spectra(arguments: dict, driver) -> dict:
    """Estimates protein secondary structure from a CD spectrum using the
    Chen, Yang & Chau (1974) empirical formula relating mean residue
    ellipticity at 222 nm to helix fraction (a simplified single-wavelength
    estimate, NOT a full basis-spectra deconvolution such as CDSSTR/CONTIN,
    which needs a reference spectral library not bundled in this
    deployment). If `temperature_data`/`thermal_cd_data` are supplied, also
    fits a two-state Boltzmann-sigmoid melting curve (`scipy.optimize.
    curve_fit`) to extract the melting temperature (Tm)."""
    validated = AnalyzeCircularDichroismSpectraArgs.model_validate(arguments or {})
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os
        import numpy as np

        sample_name = _args["sample_name"]
        sample_type = _args["sample_type"]
        output_dir = _args["output_dir"]
        wavelength_data = np.asarray(_args["wavelength_data"], dtype=float)
        cd_signal_data = np.asarray(_args["cd_signal_data"], dtype=float)

        def nearest_signal(target_wavelength):
            idx = int(np.argmin(np.abs(wavelength_data - target_wavelength)))
            return float(cd_signal_data[idx])

        if sample_type.lower() in {"protein", "peptide"}:
            signal_222 = nearest_signal(222.0)
            signal_208 = nearest_signal(208.0)
            signal_195 = nearest_signal(195.0)
            # Chen, Yang & Chau, Biochemistry 1974 -- empirical helix-content
            # formula from mean residue ellipticity (MRE) at 222 nm. Assumes
            # the input is already in MRE units (deg*cm^2/dmol); if raw
            # millidegrees were supplied this is a qualitative estimate only.
            helix_fraction = float(np.clip((-signal_222 - 3000.0) / 36000.0, 0.0, 1.0))
            r_value = (signal_222 / signal_208) if signal_208 != 0 else None
            secondary_structure = {
                "method": "Chen-Yang-Chau 1974 MRE222 empirical helix estimate",
                "signal_at_222nm": signal_222,
                "signal_at_208nm": signal_208,
                "signal_at_195nm": signal_195,
                "estimated_helix_fraction": helix_fraction,
                "r_value_222_over_208": r_value,
                "note": (
                    "R (theta222/theta208) above ~1.0 is classically associated with "
                    "coiled-coil helical bundles (Cooper & Woody 1990) rather than "
                    "isolated alpha-helices. This is a simplified single-formula "
                    "estimate, not a full basis-spectra deconvolution."
                ),
            }
        else:
            min_idx = int(np.argmin(cd_signal_data))
            max_idx = int(np.argmax(cd_signal_data))
            secondary_structure = {
                "note": (
                    f"sample_type={sample_type!r} is not 'protein'/'peptide'; the "
                    "Chen-Yang-Chau helix-content formula only applies to polypeptide "
                    "CD spectra, so only raw spectral extrema are reported."
                ),
                "min_signal": float(cd_signal_data[min_idx]),
                "min_signal_wavelength": float(wavelength_data[min_idx]),
                "max_signal": float(cd_signal_data[max_idx]),
                "max_signal_wavelength": float(wavelength_data[max_idx]),
            }

        thermal_stability = None
        temperature_data = _args.get("temperature_data")
        thermal_cd_data = _args.get("thermal_cd_data")
        if temperature_data and thermal_cd_data:
            from scipy.optimize import curve_fit

            T = np.asarray(temperature_data, dtype=float)
            S = np.asarray(thermal_cd_data, dtype=float)

            def boltzmann_sigmoid(t, folded, unfolded, tm, slope):
                return unfolded + (folded - unfolded) / (1.0 + np.exp((t - tm) / slope))

            folded0 = float(S[0])
            unfolded0 = float(S[-1])
            tm0 = float(T[int(np.argmin(np.abs(S - (folded0 + unfolded0) / 2.0)))])
            slope0 = max((float(T.max()) - float(T.min())) / 10.0, 1.0)
            try:
                popt, _ = curve_fit(
                    boltzmann_sigmoid, T, S,
                    p0=[folded0, unfolded0, tm0, slope0], maxfev=20000,
                )
                folded_hat, unfolded_hat, tm_hat, slope_hat = [float(v) for v in popt]
                pred = boltzmann_sigmoid(T, *popt)
                ss_res = float(np.sum((S - pred) ** 2))
                ss_tot = float(np.sum((S - np.mean(S)) ** 2))
                r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else None
                thermal_stability = {
                    "method": "two-state Boltzmann sigmoid fit (scipy.optimize.curve_fit)",
                    "melting_temperature": tm_hat,
                    "folded_baseline_signal": folded_hat,
                    "unfolded_baseline_signal": unfolded_hat,
                    "transition_slope_factor": slope_hat,
                    "r_squared": r_squared,
                    "fit_converged": True,
                }
            except RuntimeError as exc:
                thermal_stability = {"fit_converged": False, "error": str(exc)}

        result = {
            "sample_name": sample_name,
            "sample_type": sample_type,
            "secondary_structure": secondary_structure,
            "thermal_stability": thermal_stability,
            "output_dir": output_dir,
        }
        os.makedirs(output_dir, exist_ok=True)
        safe_name = "".join(c if c.isalnum() else "_" for c in sample_name)
        report_path = os.path.join(output_dir, f"{safe_name}_cd_analysis.json")
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh)
        result["report_path"] = report_path
        print(json.dumps(result))
        """
    )
    args = {
        "sample_name": validated.sample_name,
        "sample_type": validated.sample_type,
        "wavelength_data": validated.wavelength_data,
        "cd_signal_data": validated.cd_signal_data,
        "temperature_data": validated.temperature_data,
        "thermal_cd_data": validated.thermal_cd_data,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_rna_secondary_structure_features
# ---------------------------------------------------------------------------

_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{", ">": "<"}
_VALID_DOT_BRACKET_CHARS = set(_BRACKET_PAIRS.keys()) | set(_BRACKET_PAIRS.values()) | {"."}


class AnalyzeRnaSecondaryStructureFeaturesArgs(BaseModel):
    dot_bracket_structure: str
    sequence: Optional[str] = None

    @field_validator("dot_bracket_structure")
    @classmethod
    def _valid_dot_bracket(cls, value: str) -> str:
        if not value:
            raise ValueError("dot_bracket_structure must be non-empty")
        invalid = set(value) - _VALID_DOT_BRACKET_CHARS
        if invalid:
            raise ValueError(
                f"dot_bracket_structure contains unsupported characters: {sorted(invalid)}"
            )
        return value

    @model_validator(mode="after")
    def _sequence_length_matches(self) -> "AnalyzeRnaSecondaryStructureFeaturesArgs":
        if self.sequence is not None and len(self.sequence) != len(self.dot_bracket_structure):
            raise ValueError("sequence length must match dot_bracket_structure length")
        return self


def analyze_rna_secondary_structure_features(arguments: dict, driver) -> dict:
    """Real stack-based dot-bracket parser: recovers base pairs (supporting
    `()`, `[]`, `{}`, `<>` pseudoknot bracket alphabets), maximal nested
    helical stems, and hairpin loops (pairs whose interior contains no other
    paired position). If `sequence` is supplied, also reports GC content and
    -- via real ViennaRNA (`RNA.fold_compound(...).eval_structure(...)`,
    Turner nearest-neighbor energy model) -- the free energy of exactly this
    structure."""
    validated = AnalyzeRnaSecondaryStructureFeaturesArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json

        dot_bracket_structure = _args["dot_bracket_structure"]
        sequence = _args.get("sequence")

        pairs_map = {")": "(", "]": "[", "}": "{", ">": "<"}
        openers = set(pairs_map.values())
        closers = set(pairs_map.keys())

        stacks = {o: [] for o in openers}
        base_pairs = []
        for i, ch in enumerate(dot_bracket_structure):
            if ch in openers:
                stacks[ch].append(i)
            elif ch in closers:
                opener = pairs_map[ch]
                if not stacks[opener]:
                    raise ValueError(f"Unbalanced dot-bracket structure: unmatched {ch!r} at position {i}")
                j = stacks[opener].pop()
                base_pairs.append((j, i))
        for opener, stack in stacks.items():
            if stack:
                raise ValueError(
                    f"Unbalanced dot-bracket structure: unmatched {opener!r} at position {stack[0]}"
                )

        base_pairs.sort()
        paired_positions = set()
        for i, j in base_pairs:
            paired_positions.add(i)
            paired_positions.add(j)

        length = len(dot_bracket_structure)
        num_paired = len(paired_positions)
        num_unpaired = length - num_paired

        # Stems: maximal runs of nested, contiguous base pairs
        # (i, j), (i+1, j-1), (i+2, j-2), ...
        pair_dict = dict(base_pairs)
        stems = []
        visited = set()
        for i, j in base_pairs:
            if i in visited:
                continue
            stem = [(i, j)]
            visited.add(i)
            ni, nj = i + 1, j - 1
            while pair_dict.get(ni) == nj and ni not in visited:
                stem.append((ni, nj))
                visited.add(ni)
                ni += 1
                nj -= 1
            stems.append(stem)

        # Hairpin loops: a base pair (i, j) whose interior contains no other
        # paired position -- the minimal enclosed loop.
        hairpin_loops = []
        for i, j in base_pairs:
            if all(p not in paired_positions for p in range(i + 1, j)):
                hairpin_loops.append({"pair": [i, j], "loop_length": j - i - 1})

        gc_content = None
        if sequence:
            seq_upper = sequence.upper()
            gc_count = seq_upper.count("G") + seq_upper.count("C")
            gc_content = gc_count / len(seq_upper) if seq_upper else None

        energy_kcal_per_mol = None
        energy_method = None
        if sequence:
            try:
                import RNA
                fc = RNA.fold_compound(sequence.upper().replace("T", "U"))
                energy_kcal_per_mol = float(fc.eval_structure(dot_bracket_structure))
                energy_method = (
                    "ViennaRNA fold_compound.eval_structure (Turner 2004 "
                    "nearest-neighbor energy model)"
                )
            except ImportError:
                energy_method = "ViennaRNA python bindings not available in this environment"

        result = {
            "length": length,
            "num_base_pairs": len(base_pairs),
            "base_pairs": [[i, j] for i, j in base_pairs],
            "num_paired_positions": num_paired,
            "num_unpaired_positions": num_unpaired,
            "num_stems": len(stems),
            "stems": [[[p[0], p[1]] for p in stem] for stem in stems],
            "num_hairpin_loops": len(hairpin_loops),
            "hairpin_loops": hairpin_loops,
            "gc_content": gc_content,
            "free_energy_kcal_per_mol": energy_kcal_per_mol,
            "free_energy_method": energy_method,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "dot_bracket_structure": validated.dot_bracket_structure,
        "sequence": validated.sequence,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_protease_kinetics
# ---------------------------------------------------------------------------


class AnalyzeProteaseKineticsArgs(BaseModel):
    time_points: List[float] = Field(min_length=2)
    fluorescence_data: List[List[float]] = Field(min_length=1)
    substrate_concentrations: List[float] = Field(min_length=1)
    enzyme_concentration: float = Field(gt=0)
    output_prefix: str = "protease_kinetics"
    output_dir: str = "./"

    @model_validator(mode="after")
    def _validate_shapes(self) -> "AnalyzeProteaseKineticsArgs":
        if len(self.fluorescence_data) != len(self.substrate_concentrations):
            raise ValueError(
                "fluorescence_data must have exactly one row per substrate_concentrations entry"
            )
        for row in self.fluorescence_data:
            if len(row) != len(self.time_points):
                raise ValueError("each fluorescence_data row must have len(time_points) values")
        return self


def analyze_protease_kinetics(arguments: dict, driver) -> dict:
    """Michaelis-Menten fit from a fluorogenic protease assay: for each
    substrate concentration, the initial velocity v0 is the slope of a real
    linear regression (`scipy.stats.linregress`) of fluorescence vs
    `time_points`; the resulting v0-vs-[S] curve is then fit to the real
    Michaelis-Menten equation (`scipy.optimize.curve_fit`) to recover Vmax
    and Km, and `kcat = Vmax / enzyme_concentration`."""
    validated = AnalyzeProteaseKineticsArgs.model_validate(arguments or {})
    output_prefix = ensure_safe_relative_path(validated.output_prefix)
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os
        import numpy as np
        from scipy.optimize import curve_fit
        from scipy.stats import linregress

        time_points = np.asarray(_args["time_points"], dtype=float)
        fluorescence_data = np.asarray(_args["fluorescence_data"], dtype=float)
        substrate_concentrations = np.asarray(_args["substrate_concentrations"], dtype=float)
        enzyme_concentration = float(_args["enzyme_concentration"])
        output_prefix = _args["output_prefix"]
        output_dir = _args["output_dir"]

        initial_velocities = []
        per_concentration = []
        for conc, row in zip(substrate_concentrations, fluorescence_data):
            lin = linregress(time_points, row)
            v0 = max(float(lin.slope), 0.0)
            initial_velocities.append(v0)
            per_concentration.append({
                "substrate_concentration": float(conc),
                "initial_velocity": v0,
                "r_squared": float(lin.rvalue ** 2),
            })
        initial_velocities = np.asarray(initial_velocities, dtype=float)

        def michaelis_menten(S, vmax, km):
            return (vmax * S) / (km + S)

        vmax0 = max(float(np.max(initial_velocities)), 1e-6)
        km0 = max(float(np.median(substrate_concentrations)), 1e-6)
        popt, pcov = curve_fit(
            michaelis_menten, substrate_concentrations, initial_velocities,
            p0=[vmax0, km0], bounds=([1e-9, 1e-9], [np.inf, np.inf]), maxfev=20000,
        )
        vmax_hat, km_hat = [float(v) for v in popt]
        kcat_hat = vmax_hat / enzyme_concentration if enzyme_concentration > 0 else None
        catalytic_efficiency = (kcat_hat / km_hat) if (kcat_hat is not None and km_hat > 0) else None

        pred = michaelis_menten(substrate_concentrations, *popt)
        ss_res = float(np.sum((initial_velocities - pred) ** 2))
        ss_tot = float(np.sum((initial_velocities - np.mean(initial_velocities)) ** 2))
        r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else None

        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, f"{output_prefix}_report.json")
        result = {
            "output_prefix": output_prefix,
            "output_dir": output_dir,
            "per_concentration": per_concentration,
            "vmax": vmax_hat,
            "km": km_hat,
            "kcat": kcat_hat,
            "catalytic_efficiency_kcat_over_km": catalytic_efficiency,
            "r_squared": r_squared,
            "report_path": report_path,
        }
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh)
        print(json.dumps(result))
        """
    )
    args = {
        "time_points": validated.time_points,
        "fluorescence_data": validated.fluorescence_data,
        "substrate_concentrations": validated.substrate_concentrations,
        "enzyme_concentration": validated.enzyme_concentration,
        "output_prefix": output_prefix,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_enzyme_kinetics_assay
# ---------------------------------------------------------------------------


class ModulatorDoseResponse(BaseModel):
    """One modulator's dose-response titration: paired arrays of modulator
    concentration and the resulting reaction velocity, measured at the fixed
    assay substrate/enzyme concentrations recorded on the parent tool call."""

    concentrations: List[float] = Field(min_length=2)
    velocities: List[float] = Field(min_length=2)
    mode: Optional[str] = None

    @field_validator("mode")
    @classmethod
    def _valid_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"inhibitor", "activator"}:
            raise ValueError("mode must be 'inhibitor', 'activator', or omitted")
        return value

    @model_validator(mode="after")
    def _lengths_match(self) -> "ModulatorDoseResponse":
        if len(self.concentrations) != len(self.velocities):
            raise ValueError("concentrations and velocities must be the same length")
        return self


class AnalyzeEnzymeKineticsAssayArgs(BaseModel):
    enzyme_name: str
    substrate_concentrations: List[float] = Field(min_length=1)
    enzyme_concentration: float = Field(gt=0)
    modulators: Optional[Dict[str, ModulatorDoseResponse]] = None
    time_points: Optional[List[float]] = None
    output_dir: str = "./"

    @field_validator("enzyme_name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("enzyme_name must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _requires_modulator_data(self) -> "AnalyzeEnzymeKineticsAssayArgs":
        if not self.modulators:
            raise ValueError(
                "modulators must include at least one named condition with its own "
                "'concentrations'/'velocities' dose-response arrays -- this tool fits a "
                "real dose-response curve per modulator and has no other source of "
                "measured kinetics data to fit against, so it refuses rather than "
                "fabricating a result."
            )
        return self


def analyze_enzyme_kinetics_assay(arguments: dict, driver) -> dict:
    """Dose-dependent modulator kinetics: for every entry in `modulators`,
    fits a real four-parameter logistic (Hill) dose-response curve
    (`scipy.optimize.curve_fit`) of reaction velocity vs modulator
    concentration, the standard closed-form pharmacology/enzymology model
    for characterizing an inhibitor's IC50 or an activator's EC50 and Hill
    slope. `substrate_concentrations`/`enzyme_concentration`/`time_points`
    are recorded as the fixed assay conditions the titration was measured
    under."""
    validated = AnalyzeEnzymeKineticsAssayArgs.model_validate(arguments or {})
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import numpy as np
        from scipy.optimize import curve_fit

        enzyme_name = _args["enzyme_name"]
        substrate_concentrations = _args["substrate_concentrations"]
        enzyme_concentration = float(_args["enzyme_concentration"])
        modulators = _args["modulators"]
        output_dir = _args["output_dir"]

        def four_param_logistic(x, bottom, top, ec50, hill):
            x = np.asarray(x, dtype=float)
            ec50 = ec50 if abs(ec50) > 1e-12 else 1e-12
            return bottom + (top - bottom) / (1.0 + (x / ec50) ** hill)

        modulator_results = {}
        for name, cond in modulators.items():
            conc = np.asarray(cond["concentrations"], dtype=float)
            vel = np.asarray(cond["velocities"], dtype=float)

            bottom0 = float(np.min(vel))
            top0 = float(np.max(vel))
            positive_conc = conc[conc > 0]
            ec50_0 = float(np.median(positive_conc)) if positive_conc.size else float(np.median(conc) + 1e-6)
            increasing = vel[int(np.argmax(conc))] >= vel[int(np.argmin(conc))]
            hill0 = 1.0 if increasing else -1.0

            fit_converged = True
            try:
                popt, pcov = curve_fit(
                    four_param_logistic, conc, vel,
                    p0=[bottom0, top0, max(ec50_0, 1e-6), hill0], maxfev=20000,
                )
                bottom, top, ec50, hill = [float(v) for v in popt]
                pred = four_param_logistic(conc, *popt)
                ss_res = float(np.sum((vel - pred) ** 2))
                ss_tot = float(np.sum((vel - np.mean(vel)) ** 2))
                r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else None
            except RuntimeError:
                fit_converged = False
                bottom = top = ec50 = hill = None
                r_squared = None

            inferred_mode = "activator" if increasing else "inhibitor"
            modulator_results[name] = {
                "declared_mode": cond.get("mode"),
                "inferred_mode_from_data": inferred_mode,
                "fit_converged": fit_converged,
                "bottom_velocity": bottom,
                "top_velocity": top,
                "ec50_or_ic50": ec50,
                "hill_slope": hill,
                "r_squared": r_squared,
                "n_points": int(len(conc)),
            }

        result = {
            "enzyme_name": enzyme_name,
            "assay_substrate_concentrations": [float(s) for s in substrate_concentrations],
            "assay_enzyme_concentration": enzyme_concentration,
            "assay_time_points": _args.get("time_points"),
            "modulators": modulator_results,
            "output_dir": output_dir,
            "method": "four-parameter logistic (Hill) dose-response fit per modulator",
        }
        print(json.dumps(result))
        """
    )
    args = {
        "enzyme_name": validated.enzyme_name,
        "substrate_concentrations": validated.substrate_concentrations,
        "enzyme_concentration": validated.enzyme_concentration,
        "modulators": {
            name: cond.model_dump() for name, cond in (validated.modulators or {}).items()
        },
        "time_points": validated.time_points,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_itc_binding_thermodynamics
# ---------------------------------------------------------------------------


class AnalyzeItcBindingThermodynamicsArgs(BaseModel):
    itc_data_path: Optional[str] = None
    itc_data: Optional[List[List[float]]] = None
    temperature: float = Field(default=298.15, gt=0)
    protein_concentration: Optional[float] = Field(default=None, gt=0)
    ligand_concentration: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _requires_a_data_source(self) -> "AnalyzeItcBindingThermodynamicsArgs":
        if not self.itc_data_path and not self.itc_data:
            raise ValueError("either itc_data_path or itc_data must be provided")
        if self.itc_data is not None:
            if len(self.itc_data) < 4:
                raise ValueError("itc_data must contain at least 4 [molar_ratio, heat] rows")
            for row in self.itc_data:
                if len(row) != 2:
                    raise ValueError(
                        "itc_data rows must be [molar_ratio, heat_kcal_per_mol_injectant] pairs"
                    )
        return self


def analyze_itc_binding_thermodynamics(arguments: dict, driver) -> dict:
    """Fits a real single-site Wiseman binding isotherm (Wiseman, Williston,
    Brandts & Lin, Anal. Biochem. 1989) to isothermal titration calorimetry
    data -- `[molar_ratio, heat]` pairs, either given directly (`itc_data`)
    or read from `itc_data_path` (CSV, first two columns) -- via
    `scipy.optimize.curve_fit`, recovering stoichiometry (n), association
    constant (Ka) / Kd, binding enthalpy (deltaH), and (from `temperature`)
    the derived deltaG = -RT*ln(Ka) and deltaS = (deltaH - deltaG) / T."""
    validated = AnalyzeItcBindingThermodynamicsArgs.model_validate(arguments or {})
    itc_data_path = (
        ensure_safe_relative_path(validated.itc_data_path) if validated.itc_data_path else None
    )

    script_body = _dedent(
        """
        import csv
        import json
        import numpy as np
        from scipy.optimize import curve_fit

        itc_data_path = _args.get("itc_data_path")
        itc_data = _args.get("itc_data")
        temperature = float(_args["temperature"])
        protein_concentration = _args.get("protein_concentration")

        if itc_data is not None:
            data = np.asarray(itc_data, dtype=float)
        else:
            rows = []
            with open(itc_data_path, encoding="utf-8") as fh:
                reader = csv.reader(fh)
                first = next(reader, None)
                if first is not None:
                    try:
                        rows.append([float(first[0]), float(first[1])])
                    except ValueError:
                        pass  # header row
                for r in reader:
                    if len(r) >= 2:
                        rows.append([float(r[0]), float(r[1])])
            data = np.asarray(rows, dtype=float)

        if data.ndim != 2 or data.shape[1] != 2 or data.shape[0] < 4:
            raise ValueError("ITC data must have at least 4 rows of [molar_ratio, heat] pairs")

        molar_ratio = data[:, 0]
        heat = data[:, 1]

        Mt = float(protein_concentration) if protein_concentration else 1.0
        R_GAS = 1.987204e-3  # kcal / (mol * K)

        def wiseman_isotherm(Xr, n, log_ka, dH):
            Ka = 10.0 ** log_ka
            n = n if abs(n) > 1e-6 else 1e-6
            a = 1.0 + Xr / n + 1.0 / (n * Ka * Mt)
            inside = np.clip(a ** 2 - 4.0 * Xr / n, 0.0, None)
            return dH * 0.5 * (a - np.sqrt(inside))

        n0 = 1.0
        log_ka0 = 5.0  # Ka ~ 1e5 M^-1
        dH0 = float(heat[0]) if heat[0] != 0 else -5.0
        popt, pcov = curve_fit(
            wiseman_isotherm, molar_ratio, heat,
            p0=[n0, log_ka0, dH0], maxfev=20000,
        )
        n_hat, log_ka_hat, dH_hat = [float(v) for v in popt]
        ka_hat = 10.0 ** log_ka_hat
        kd_hat = 1.0 / ka_hat if ka_hat > 0 else None
        dG_hat = -R_GAS * temperature * np.log(ka_hat) if ka_hat > 0 else None
        dS_hat_kcal = (dH_hat - dG_hat) / temperature if dG_hat is not None else None
        dS_hat_cal = dS_hat_kcal * 1000.0 if dS_hat_kcal is not None else None

        pred = wiseman_isotherm(molar_ratio, *popt)
        ss_res = float(np.sum((heat - pred) ** 2))
        ss_tot = float(np.sum((heat - np.mean(heat)) ** 2))
        r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else None

        result = {
            "method": "Wiseman single-site binding isotherm (Wiseman et al. 1989)",
            "stoichiometry_n": n_hat,
            "association_constant_Ka_per_M": ka_hat,
            "dissociation_constant_Kd_M": kd_hat,
            "binding_enthalpy_dH_kcal_per_mol": dH_hat,
            "binding_free_energy_dG_kcal_per_mol": dG_hat,
            "binding_entropy_dS_cal_per_mol_K": dS_hat_cal,
            "temperature_K": temperature,
            "r_squared": r_squared,
            "n_data_points": int(data.shape[0]),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "itc_data_path": itc_data_path,
        "itc_data": validated.itc_data,
        "temperature": validated.temperature,
        "protein_concentration": validated.protein_concentration,
        "ligand_concentration": validated.ligand_concentration,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_protein_conservation
# ---------------------------------------------------------------------------


class AnalyzeProteinConservationArgs(BaseModel):
    protein_sequences: List[str] = Field(min_length=2)
    output_dir: str = "./"

    @field_validator("protein_sequences")
    @classmethod
    def _non_empty_sequences(cls, value: List[str]) -> List[str]:
        cleaned = [s.strip() for s in value]
        if any(not s for s in cleaned):
            raise ValueError("protein_sequences must not contain empty strings")
        return cleaned


def analyze_protein_conservation(arguments: dict, driver) -> dict:
    """Multiple sequence alignment (real `mafft --auto` CLI call, argv-list
    `subprocess.run`, no shell string interpolation) followed by real
    per-column identity-fraction conservation scoring, reporting a consensus
    sequence and the contiguous regions whose per-column conservation is
    >= 0.8 (candidate conserved/functional regions)."""
    validated = AnalyzeProteinConservationArgs.model_validate(arguments or {})
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os
        import subprocess
        from collections import Counter

        protein_sequences = _args["protein_sequences"]
        output_dir = _args["output_dir"]

        os.makedirs(output_dir, exist_ok=True)
        input_fasta = os.path.join(output_dir, "conservation_input.fasta")
        with open(input_fasta, "w", encoding="utf-8") as fh:
            for i, seq in enumerate(protein_sequences):
                fh.write(f">seq_{i}\\n{seq}\\n")

        aligned_fasta = os.path.join(output_dir, "conservation_aligned.fasta")
        with open(aligned_fasta, "w") as out_fh:
            proc = subprocess.run(
                ["mafft", "--auto", input_fasta],
                stdout=out_fh, stderr=subprocess.PIPE, text=True,
            )
        if proc.returncode != 0:
            raise RuntimeError(f"mafft failed: {proc.stderr}")

        from Bio import SeqIO
        records = list(SeqIO.parse(aligned_fasta, "fasta"))
        aligned_seqs = [str(r.seq).upper() for r in records]
        alignment_length = len(aligned_seqs[0]) if aligned_seqs else 0

        conservation_scores = []
        consensus = []
        for col in range(alignment_length):
            residues = [seq[col] for seq in aligned_seqs if col < len(seq)]
            non_gap = [r for r in residues if r != "-"]
            if not non_gap:
                conservation_scores.append(0.0)
                consensus.append("-")
                continue
            counts = Counter(non_gap)
            most_common_residue, most_common_count = counts.most_common(1)[0]
            conservation_scores.append(most_common_count / len(residues))
            consensus.append(most_common_residue)

        threshold = 0.8
        conserved_regions = []
        start = None
        for i, score in enumerate(conservation_scores):
            if score >= threshold:
                if start is None:
                    start = i
            elif start is not None:
                conserved_regions.append({"start": start, "end": i - 1, "length": i - start})
                start = None
        if start is not None:
            conserved_regions.append(
                {"start": start, "end": alignment_length - 1, "length": alignment_length - start}
            )

        result = {
            "n_sequences": len(protein_sequences),
            "alignment_length": alignment_length,
            "alignment_file": aligned_fasta,
            "consensus_sequence": "".join(consensus),
            "conservation_scores": conservation_scores,
            "conserved_regions": conserved_regions,
            "conservation_threshold": threshold,
            "output_dir": output_dir,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "protein_sequences": validated.protein_sequences,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_atp_luminescence_assay
# ---------------------------------------------------------------------------


class AnalyzeAtpLuminescenceAssayArgs(BaseModel):
    data_file: str
    standard_curve_file: str
    normalization_method: str = "cell_count"
    normalization_data: Optional[Union[str, Dict[str, float]]] = None

    @field_validator("data_file", "standard_curve_file")
    @classmethod
    def _non_empty_path(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty path")
        return value


def analyze_atp_luminescence_assay(arguments: dict, driver) -> dict:
    """Real linear-regression (`scipy.stats.linregress`) ATP standard curve
    (known concentration vs luminescence, read from `standard_curve_file`
    CSV, columns `concentration`/`luminescence`) applied to interpolate ATP
    concentration for every sample in `data_file` CSV (column
    `luminescence`, optional `sample_id`). If `normalization_data` is
    supplied (either an inline `{sample_id: value}` mapping or a path to a
    two-column CSV), each sample's ATP value is divided by its normalization
    value (e.g. cell count)."""
    validated = AnalyzeAtpLuminescenceAssayArgs.model_validate(arguments or {})
    data_file = ensure_safe_relative_path(validated.data_file)
    standard_curve_file = ensure_safe_relative_path(validated.standard_curve_file)
    normalization_data_path = None
    normalization_data_inline = None
    if isinstance(validated.normalization_data, str):
        normalization_data_path = ensure_safe_relative_path(validated.normalization_data)
    elif isinstance(validated.normalization_data, dict):
        normalization_data_inline = validated.normalization_data

    script_body = _dedent(
        """
        import json
        import pandas as pd
        from scipy.stats import linregress

        data_file = _args["data_file"]
        standard_curve_file = _args["standard_curve_file"]
        normalization_method = _args["normalization_method"]
        normalization_data_path = _args.get("normalization_data_path")
        normalization_data_inline = _args.get("normalization_data_inline")

        std_df = pd.read_csv(standard_curve_file)
        if not {"concentration", "luminescence"}.issubset(std_df.columns):
            raise ValueError("standard_curve_file must have 'concentration' and 'luminescence' columns")

        lin = linregress(
            std_df["luminescence"].to_numpy(dtype=float),
            std_df["concentration"].to_numpy(dtype=float),
        )
        r_squared = float(lin.rvalue ** 2)

        data_df = pd.read_csv(data_file)
        if "luminescence" not in data_df.columns:
            raise ValueError("data_file must have a 'luminescence' column")
        if "sample_id" not in data_df.columns:
            data_df["sample_id"] = [f"sample_{i}" for i in range(len(data_df))]

        data_df["atp_concentration"] = lin.slope * data_df["luminescence"] + lin.intercept

        norm_map = None
        if normalization_data_path:
            norm_df = pd.read_csv(normalization_data_path)
            norm_map = dict(zip(norm_df.iloc[:, 0].astype(str), norm_df.iloc[:, 1].astype(float)))
        elif normalization_data_inline:
            norm_map = {str(k): float(v) for k, v in normalization_data_inline.items()}

        if norm_map is not None:
            data_df["normalization_value"] = data_df["sample_id"].astype(str).map(norm_map)
            data_df["normalized_atp"] = data_df["atp_concentration"] / data_df["normalization_value"]
        else:
            data_df["normalized_atp"] = data_df["atp_concentration"]

        result = {
            "standard_curve_slope": float(lin.slope),
            "standard_curve_intercept": float(lin.intercept),
            "standard_curve_r_squared": r_squared,
            "normalization_method": normalization_method,
            "normalized": norm_map is not None,
            "samples": json.loads(data_df.to_json(orient="records")),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "data_file": data_file,
        "standard_curve_file": standard_curve_file,
        "normalization_method": validated.normalization_method,
        "normalization_data_path": normalization_data_path,
        "normalization_data_inline": normalization_data_inline,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_bacterial_growth_curve / analyze_bacterial_growth_rate
#
# Same family (per action_tool_catalog.md): both fit the Zwietering et al.
# (1990, Appl. Environ. Microbiol. 56:1875-1881) modified logistic bacterial
# growth model to OD600 vs time. They share this one script body -- each
# handler just maps its own differently-named OD argument
# (`od_values`/`od_measurements`) into the same `od_values` key.
# ---------------------------------------------------------------------------

_BACTERIAL_GROWTH_SCRIPT_BODY = _dedent(
    """
    import json
    import os
    import numpy as np
    from scipy.optimize import curve_fit

    time_points = np.asarray(_args["time_points"], dtype=float)
    od_values = np.asarray(_args["od_values"], dtype=float)
    strain_name = _args["strain_name"]
    output_dir = _args["output_dir"]

    if time_points.shape[0] != od_values.shape[0]:
        raise ValueError("time_points and OD values must be the same length")
    if np.any(od_values <= 0):
        raise ValueError("OD values must be strictly positive to fit a logistic growth model")

    od0 = float(od_values[0])
    y = np.log(od_values / od0)  # relative log-growth, y(0) = 0

    def zwietering_modified_logistic(t, A, mu_m, lam):
        # Zwietering et al. 1990 (Appl. Environ. Microbiol. 56:1875-1881),
        # modified logistic growth model: A = asymptotic log fold-change,
        # mu_m = maximum specific growth rate, lam = lag time.
        return A / (1.0 + np.exp((4.0 * mu_m / A) * (lam - t) + 2.0))

    A0 = max(float(np.max(y)), 1e-3)
    dt = np.diff(time_points)
    dy = np.diff(y)
    with np.errstate(divide="ignore", invalid="ignore"):
        slopes = np.where(dt > 0, dy / dt, 0.0)
    mu_m0 = max(float(np.max(slopes)) if slopes.size else 0.1, 1e-3)
    lam0 = float(time_points[0])

    popt, pcov = curve_fit(
        zwietering_modified_logistic, time_points, y,
        p0=[A0, mu_m0, lam0],
        bounds=([1e-6, 1e-6, -np.inf], [np.inf, np.inf, np.inf]),
        maxfev=20000,
    )
    A_hat, mu_m_hat, lambda_hat = [float(v) for v in popt]

    doubling_time = float(np.log(2) / mu_m_hat) if mu_m_hat > 0 else None
    carrying_capacity_od = float(od0 * np.exp(A_hat))
    pred = zwietering_modified_logistic(time_points, *popt)
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else None

    os.makedirs(output_dir, exist_ok=True)
    safe_strain = "".join(c if c.isalnum() else "_" for c in strain_name)
    report_path = os.path.join(output_dir, f"{safe_strain}_growth_curve.json")
    result = {
        "strain_name": strain_name,
        "method": "Zwietering et al. 1990 modified logistic growth model",
        "initial_od": od0,
        "max_growth_rate_per_time_unit": mu_m_hat,
        "lag_time": lambda_hat,
        "asymptotic_log_fold_change": A_hat,
        "carrying_capacity_od": carrying_capacity_od,
        "doubling_time": doubling_time,
        "r_squared": r_squared,
        "output_dir": output_dir,
        "report_path": report_path,
    }
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    print(json.dumps(result))
    """
)


class AnalyzeBacterialGrowthCurveArgs(BaseModel):
    time_points: List[float] = Field(min_length=3)
    od_values: List[float] = Field(min_length=3)
    strain_name: str
    output_dir: str = "."

    @field_validator("strain_name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("strain_name must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _lengths_match(self) -> "AnalyzeBacterialGrowthCurveArgs":
        if len(self.time_points) != len(self.od_values):
            raise ValueError("time_points and od_values must be the same length")
        return self


def analyze_bacterial_growth_curve(arguments: dict, driver) -> dict:
    """Fits the Zwietering et al. (1990) modified logistic growth model
    (`scipy.optimize.curve_fit`) to `od_values` vs `time_points`, returning
    the maximum specific growth rate, lag-phase duration, doubling time, and
    estimated carrying capacity (OD)."""
    validated = AnalyzeBacterialGrowthCurveArgs.model_validate(arguments or {})
    output_dir = ensure_safe_relative_path(validated.output_dir)

    args = {
        "time_points": validated.time_points,
        "od_values": validated.od_values,
        "strain_name": validated.strain_name,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=_BACTERIAL_GROWTH_SCRIPT_BODY, args=args)


class AnalyzeBacterialGrowthRateArgs(BaseModel):
    time_points: List[float] = Field(min_length=3)
    od_measurements: List[float] = Field(min_length=3)
    strain_name: str = "Unknown strain"
    output_dir: str = "./"

    @model_validator(mode="after")
    def _lengths_match(self) -> "AnalyzeBacterialGrowthRateArgs":
        if len(self.time_points) != len(self.od_measurements):
            raise ValueError("time_points and od_measurements must be the same length")
        return self


def analyze_bacterial_growth_rate(arguments: dict, driver) -> dict:
    """OD600-based sibling of `analyze_bacterial_growth_curve` (same
    Zwietering et al. 1990 modified logistic model, same script body) --
    differs only in its OD argument's name (`od_measurements`) and
    `strain_name`'s default."""
    validated = AnalyzeBacterialGrowthRateArgs.model_validate(arguments or {})
    output_dir = ensure_safe_relative_path(validated.output_dir)

    args = {
        "time_points": validated.time_points,
        "od_values": validated.od_measurements,
        "strain_name": validated.strain_name,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=_BACTERIAL_GROWTH_SCRIPT_BODY, args=args)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_TOOL_HANDLERS = {
    "analyze_circular_dichroism_spectra": analyze_circular_dichroism_spectra,
    "analyze_rna_secondary_structure_features": analyze_rna_secondary_structure_features,
    "analyze_protease_kinetics": analyze_protease_kinetics,
    "analyze_enzyme_kinetics_assay": analyze_enzyme_kinetics_assay,
    "analyze_itc_binding_thermodynamics": analyze_itc_binding_thermodynamics,
    "analyze_protein_conservation": analyze_protein_conservation,
    "analyze_atp_luminescence_assay": analyze_atp_luminescence_assay,
    "analyze_bacterial_growth_curve": analyze_bacterial_growth_curve,
    "analyze_bacterial_growth_rate": analyze_bacterial_growth_rate,
}


def register_biophysics_assays_tools(registry, driver) -> List[str]:
    """Registers every Biophysics & biochemical assays action tool into
    `registry`, each bound to the shared sandbox `driver`. Returns the list
    of registered tool names."""
    for name, handler in _TOOL_HANDLERS.items():
        registry.register_server(name, functools.partial(handler, driver=driver))
    return list(_TOOL_HANDLERS.keys())
