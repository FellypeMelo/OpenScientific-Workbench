"""Synthetic biology & systems biology action tools (Fase 5).

Implements every tool listed under the "Categoria: Synthetic biology &
systems biology" heading of `backend/docs/tools/action_tool_catalog.md`.
Every tool in this category is Tier A or Tier B (no Tier D entries here --
nothing in this category needs a proprietary pretrained checkpoint or a GPU
cluster) and therefore runs its real scientific logic inside the sandbox via
`run_in_sandbox` (see `_sandbox_tool_base.py`'s module docstring for exactly
why -- LLM-influenced arguments never reach an in-process biopython/scipy/
cobra/libsbml import in this trusted backend process).

Per-tool tiering (see `action_tool_catalog.md` for the authoritative source,
this is a recap, not a re-derivation):

- Tier A (deterministic real lib, no statistical model):
  `engineer_bacterial_genome_for_therapeutic_delivery` (Biopython sequence
  assembly/insertion), `analyze_barcode_sequencing_data` (Biopython
  FASTA/FASTQ parsing + regex barcode extraction/counting),
  `create_biochemical_network_sbml_model` (real `python-libsbml` model
  construction), `optimize_codons_for_heterologous_expression` (real
  Codon-Adaptation-Index-based codon-usage optimization),
  `identify_fas_functional_domains` (simplified regex-motif domain screen,
  explicitly documented as such -- not a Pfam/HMMER call),
  `perform_flux_balance_analysis` (real `cobra` FBA),
  `compare_protein_structures` (real Biopython `Bio.PDB` Kabsch
  superposition/RMSD).
- Tier B (real numerical method, not a pretrained checkpoint):
  `analyze_bifurcation_diagram` (real `scipy.signal` local-extrema-based
  bifurcation-diagram construction from a parameter sweep of time series),
  `simulate_gene_circuit_with_growth_feedback`,
  `simulate_metabolic_network_perturbation`,
  `simulate_protein_signaling_network`,
  `simulate_renin_angiotensin_system_dynamics`, and
  `simulate_whole_cell_ode_model` (all five real `scipy.integrate.solve_ivp`
  ODE integrations, sharing ONE integration+result-formatting core --
  `_ode_integration_and_report` below -- per this category's catalog note
  that `simulate_whole_cell_ode_model` is the generic building block the
  other four are specific parameterizations of),
  `model_protein_dimerization_network` (real coupled mass-action equilibrium
  solve via `scipy.optimize.least_squares`), and
  `analyze_in_vitro_drug_release_kinetics` (real zero-order/first-order/
  Higuchi model comparison via `scipy.optimize.curve_fit`).

`simulate_whole_cell_ode_model`'s `ode_function` argument is a small
WHITELIST of named built-in right-hand-side systems (never LLM-supplied
Python source -- there is no `eval` of caller input anywhere in this
module), consistent with this category's other simulate_* tools, none of
which accept arbitrary caller-supplied code either.

Every file-path-shaped argument (`bacterial_genome_file`, `input_file`,
`model_file`, `pdb_file1`/`pdb_file2`, `output_file`, `output_prefix`,
`output_dir`) is passed through `ensure_safe_relative_path` before being
handed to the sandbox.
"""
import functools
import textwrap
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

from src.domain.services.path_guard import ensure_safe_relative_path
from src.infrastructure.tools._sandbox_tool_base import run_in_sandbox


def _dedent(script: str) -> str:
    """Strips this module's Python-source indentation off a `script_body`
    literal so the code that actually reaches the sandbox starts every line
    at column 0 (required -- `run_in_sandbox` concatenates `script_body`
    directly after its own top-level `_args` loading preamble)."""
    return textwrap.dedent(script).strip("\n")


def _ode_integration_and_report(
    *,
    y0_expr: str,
    rhs_args_expr: str,
    extra_fields_expr: str = "{}",
    rhs_name: str = "_rhs",
    time_span_expr: str = "time_span",
    time_points_expr: str = "time_points",
    method_expr: str = "method",
) -> str:
    """Shared `scipy.integrate.solve_ivp` driver + JSON-result trailer,
    textually reused (via this ONE Python function) by every ODE-based tool
    in this module -- this is `action_tool_catalog.md`'s "generic
    scipy.integrate.solve_ivp building block"
    (`simulate_whole_cell_ode_model`) that `simulate_gene_circuit_with_
    growth_feedback`, `simulate_metabolic_network_perturbation`,
    `simulate_protein_signaling_network`, and
    `simulate_renin_angiotensin_system_dynamics` are documented as specific
    parameterizations of. The actual `solve_ivp(...)` call and result-JSON
    assembly exist in exactly ONE place in this module's source (this
    function), not five.

    Every caller must have already defined, at the point this text is
    spliced in: `np`, `json`, `solve_ivp` (imported), a callable named
    `rhs_name` with signature `(t, y, *rhs_args)`, an initial-state
    expression `y0_expr`, and variables named `time_span_expr`/
    `time_points_expr`/`method_expr` (or overridden names for any of those).
    """
    return _dedent(
        f"""
        t_eval = np.linspace({time_span_expr}[0], {time_span_expr}[1], {time_points_expr})
        _sol = solve_ivp(
            {rhs_name}, {time_span_expr}, {y0_expr}, method={method_expr},
            args={rhs_args_expr}, t_eval=t_eval,
        )
        _result = {{
            "success": bool(_sol.success),
            "message": _sol.message,
            "t": _sol.t.tolist(),
            "y": _sol.y.tolist(),
            "method": {method_expr},
        }}
        _result.update({extra_fields_expr})
        print(json.dumps(_result))
        """
    )


# ---------------------------------------------------------------------------
# engineer_bacterial_genome_for_therapeutic_delivery
# ---------------------------------------------------------------------------


class GeneticPartsSpec(BaseModel):
    promoters: List[str] = Field(default_factory=list)
    genes: List[str] = Field(default_factory=list)
    terminators: List[str] = Field(default_factory=list)
    cargo: List[str] = Field(default_factory=list)
    insertion_position: Optional[int] = None

    @field_validator("promoters", "genes", "terminators", "cargo")
    @classmethod
    def _clean_parts(cls, value: List[str]) -> List[str]:
        cleaned = []
        for seq in value:
            seq = str(seq).strip().upper()
            if not seq:
                raise ValueError("genetic part sequences must be non-empty")
            if not set(seq) <= set("ACGTN"):
                raise ValueError(f"genetic part sequence contains non-ACGTN characters: {seq!r}")
            cleaned.append(seq)
        return cleaned


class EngineerBacterialGenomeArgs(BaseModel):
    bacterial_genome_file: str
    genetic_parts: GeneticPartsSpec

    @model_validator(mode="after")
    def _has_something_to_insert(self) -> "EngineerBacterialGenomeArgs":
        if not (self.genetic_parts.genes or self.genetic_parts.cargo):
            raise ValueError("genetic_parts must include at least one of 'genes' or 'cargo'")
        return self


def engineer_bacterial_genome_for_therapeutic_delivery(arguments: dict, driver) -> dict:
    """Assembles a synthetic therapeutic-delivery construct (promoters +
    genes + cargo + terminators, concatenated in that canonical order) and
    inserts it into a bacterial genome sequence read from
    `bacterial_genome_file` (Biopython `Bio.SeqIO`, FASTA). This is real
    sequence concatenation/insertion, not a wet-lab transformation result."""
    validated = EngineerBacterialGenomeArgs.model_validate(arguments or {})
    genome_file = ensure_safe_relative_path(validated.bacterial_genome_file)

    script_body = _dedent(
        """
        import json
        from Bio import SeqIO

        parts = _args["genetic_parts"]
        genome_file = _args["bacterial_genome_file"]

        record = next(SeqIO.parse(genome_file, "fasta"))
        genome_seq = str(record.seq).upper()
        genome_length_before = len(genome_seq)

        construct = (
            "".join(parts["promoters"]) + "".join(parts["genes"])
            + "".join(parts["cargo"]) + "".join(parts["terminators"])
        )
        if not construct:
            raise ValueError("assembled construct is empty")

        insertion_position = parts.get("insertion_position")
        if insertion_position is None:
            insertion_position = genome_length_before
        insertion_position = max(0, min(int(insertion_position), genome_length_before))

        engineered_seq = (
            genome_seq[:insertion_position] + construct + genome_seq[insertion_position:]
        )
        gc = (
            (engineered_seq.count("G") + engineered_seq.count("C")) / len(engineered_seq)
            if engineered_seq else 0.0
        )
        construct_gc = (
            (construct.count("G") + construct.count("C")) / len(construct) if construct else 0.0
        )

        output_path = "engineered_genome.fasta"
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(f">{record.id}_engineered\\n")
            for i in range(0, len(engineered_seq), 70):
                fh.write(engineered_seq[i:i + 70] + "\\n")

        result = {
            "output_file": output_path,
            "genome_id": record.id,
            "genome_length_before": genome_length_before,
            "genome_length_after": len(engineered_seq),
            "construct_length": len(construct),
            "construct_gc_content": construct_gc,
            "engineered_genome_gc_content": gc,
            "insertion_position": insertion_position,
            "num_promoters": len(parts["promoters"]),
            "num_genes": len(parts["genes"]),
            "num_cargo_elements": len(parts["cargo"]),
            "num_terminators": len(parts["terminators"]),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "bacterial_genome_file": genome_file,
        "genetic_parts": validated.genetic_parts.model_dump(),
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_barcode_sequencing_data
# ---------------------------------------------------------------------------


class AnalyzeBarcodeSequencingDataArgs(BaseModel):
    input_file: str
    barcode_pattern: Optional[str] = None
    flanking_seq_5prime: Optional[str] = None
    flanking_seq_3prime: Optional[str] = None
    min_count: int = Field(default=5, ge=1)
    output_dir: str = "./results"

    @model_validator(mode="after")
    def _has_extraction_strategy(self) -> "AnalyzeBarcodeSequencingDataArgs":
        has_flanks = bool(self.flanking_seq_5prime and self.flanking_seq_3prime)
        has_pattern = bool(self.barcode_pattern)
        if not has_flanks and not has_pattern:
            raise ValueError(
                "provide either barcode_pattern, or both flanking_seq_5prime and "
                "flanking_seq_3prime"
            )
        return self


def analyze_barcode_sequencing_data(arguments: dict, driver) -> dict:
    """Extracts and quantifies DNA barcodes from a FASTA/FASTQ (optionally
    gzip-compressed) read file (Biopython `Bio.SeqIO`, format auto-detected
    by extension): between two constant flanking sequences (regex capture)
    when both `flanking_seq_5prime`/`flanking_seq_3prime` are given, as a
    fixed-length prefix window when `barcode_pattern` is an `N`-only length
    pattern (e.g. `"N"*20`), or as an arbitrary regex otherwise. Reports
    per-barcode counts filtered at `min_count`, the number of unique
    lineages passing that threshold, and the Shannon diversity index of the
    filtered barcode distribution."""
    validated = AnalyzeBarcodeSequencingDataArgs.model_validate(arguments or {})
    input_file = ensure_safe_relative_path(validated.input_file)
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import csv
        import json
        import math
        import os
        import re
        from collections import Counter
        from Bio import SeqIO

        input_file = _args["input_file"]
        barcode_pattern = _args.get("barcode_pattern")
        flank5 = _args.get("flanking_seq_5prime")
        flank3 = _args.get("flanking_seq_3prime")
        min_count = int(_args["min_count"])
        output_dir = _args["output_dir"]

        lower_name = input_file.lower()
        fmt = "fastq" if any(lower_name.endswith(ext) for ext in (
            ".fastq", ".fq", ".fastq.gz", ".fq.gz"
        )) else "fasta"
        open_fn = open
        if lower_name.endswith(".gz"):
            import gzip
            open_fn = gzip.open

        if flank5 and flank3:
            mode = "flanking"
            extractor = re.compile(re.escape(flank5.upper()) + "(.*?)" + re.escape(flank3.upper()))
        elif barcode_pattern and set(barcode_pattern.upper()) == {"N"}:
            mode = "fixed_length"
            barcode_len = len(barcode_pattern)
        else:
            mode = "regex"
            extractor = re.compile(barcode_pattern, re.IGNORECASE)

        counts = Counter()
        n_reads = 0
        n_extracted = 0
        with open_fn(input_file, "rt") as fh:
            for record in SeqIO.parse(fh, fmt):
                n_reads += 1
                seq = str(record.seq).upper()
                barcode = None
                if mode == "flanking":
                    match = extractor.search(seq)
                    if match:
                        barcode = match.group(1)
                elif mode == "fixed_length":
                    if len(seq) >= barcode_len:
                        barcode = seq[:barcode_len]
                else:
                    match = extractor.search(seq)
                    if match:
                        barcode = match.group(0)
                if barcode:
                    counts[barcode] += 1
                    n_extracted += 1

        filtered = {bc: c for bc, c in counts.items() if c >= min_count}
        total_filtered_reads = sum(filtered.values())
        shannon = 0.0
        if total_filtered_reads > 0:
            for c in filtered.values():
                p = c / total_filtered_reads
                shannon -= p * math.log(p)

        os.makedirs(output_dir, exist_ok=True)
        out_csv = os.path.join(output_dir, "barcode_counts.csv")
        ranked = sorted(filtered.items(), key=lambda kv: -kv[1])
        with open(out_csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["barcode", "count"])
            for bc, c in ranked:
                writer.writerow([bc, c])

        result = {
            "output_file": out_csv,
            "n_reads_total": n_reads,
            "n_barcodes_extracted": n_extracted,
            "n_unique_barcodes_raw": len(counts),
            "n_unique_barcodes_passing_min_count": len(filtered),
            "min_count": min_count,
            "shannon_diversity_index": shannon,
            "top_barcodes": ranked[:20],
        }
        print(json.dumps(result))
        """
    )
    args = {
        "input_file": input_file,
        "barcode_pattern": validated.barcode_pattern,
        "flanking_seq_5prime": validated.flanking_seq_5prime,
        "flanking_seq_3prime": validated.flanking_seq_3prime,
        "min_count": validated.min_count,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_bifurcation_diagram
# ---------------------------------------------------------------------------


class AnalyzeBifurcationDiagramArgs(BaseModel):
    time_series_data: List[List[float]]
    parameter_values: List[float]
    system_name: str = "Dynamical System"
    output_dir: str = "./"

    @model_validator(mode="after")
    def _shapes_match(self) -> "AnalyzeBifurcationDiagramArgs":
        if len(self.time_series_data) != len(self.parameter_values):
            raise ValueError(
                "time_series_data must have one row (time series) per entry in "
                "parameter_values"
            )
        if not self.time_series_data or any(len(row) < 4 for row in self.time_series_data):
            raise ValueError("each time series must have at least 4 samples")
        return self


def analyze_bifurcation_diagram(arguments: dict, driver) -> dict:
    """Constructs a bifurcation diagram from a parameter sweep of time
    series: for each parameter value's series, discards the first half as
    transient, finds local maxima of the remaining trajectory
    (`scipy.signal.argrelextrema`) as a Poincare-section-style sample of the
    long-term attractor, and reports those extrema against the parameter
    value -- a period-1 fixed point yields one distinct extremum, a
    period-N limit cycle yields N, a chaotic regime yields many. This is a
    real, standard time-series-based bifurcation-diagram construction, not
    a from-scratch dynamical-systems solver for an arbitrary model (the
    caller supplies the time series; this tool characterizes it)."""
    validated = AnalyzeBifurcationDiagramArgs.model_validate(arguments or {})
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os
        import numpy as np
        from scipy.signal import argrelextrema
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        time_series_data = _args["time_series_data"]
        parameter_values = _args["parameter_values"]
        system_name = _args["system_name"]
        output_dir = _args["output_dir"]

        os.makedirs(output_dir, exist_ok=True)

        plot_params, plot_values, branch_counts = [], [], []
        for series, p in zip(time_series_data, parameter_values):
            series = np.asarray(series, dtype=float)
            transient_cutoff = len(series) // 2
            steady = series[transient_cutoff:]
            maxima_idx = argrelextrema(steady, np.greater_equal, order=1)[0]
            maxima_idx = maxima_idx[(maxima_idx > 0) & (maxima_idx < len(steady) - 1)]
            extrema = (
                np.unique(np.round(steady[maxima_idx], 6)) if len(maxima_idx)
                else np.array([steady[-1]])
            )
            branch_counts.append(int(len(extrema)))
            for value in extrema:
                plot_params.append(float(p))
                plot_values.append(float(value))

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.scatter(plot_params, plot_values, s=3, color="black")
        ax.set_xlabel("Parameter value")
        ax.set_ylabel("Local maxima (steady-state samples)")
        ax.set_title(f"Bifurcation diagram: {system_name}")
        plot_path = os.path.join(output_dir, "bifurcation_diagram.png")
        fig.tight_layout()
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)

        classifications = []
        for n in branch_counts:
            if n <= 1:
                classifications.append("fixed_point")
            elif n <= 8:
                classifications.append(f"period_{n}")
            else:
                classifications.append("likely_chaotic")

        bifurcation_points = [
            float(parameter_values[i])
            for i in range(1, len(classifications))
            if classifications[i] != classifications[i - 1]
        ]

        result = {
            "system_name": system_name,
            "plot_path": plot_path,
            "n_parameter_values": len(parameter_values),
            "branch_counts": branch_counts,
            "classifications": classifications,
            "bifurcation_points": bifurcation_points,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "time_series_data": validated.time_series_data,
        "parameter_values": validated.parameter_values,
        "system_name": validated.system_name,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# create_biochemical_network_sbml_model
# ---------------------------------------------------------------------------


class ReactionSpec(BaseModel):
    id: str
    substrates: Dict[str, float] = Field(default_factory=dict)
    products: Dict[str, float] = Field(default_factory=dict)
    reversible: bool = False

    @field_validator("id")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("reaction id must be non-empty")
        return value

    @model_validator(mode="after")
    def _has_species(self) -> "ReactionSpec":
        if not self.substrates and not self.products:
            raise ValueError(f"reaction {self.id!r} must have at least one substrate or product")
        return self


class CreateBiochemicalNetworkSbmlModelArgs(BaseModel):
    reaction_network: List[ReactionSpec] = Field(min_length=1)
    kinetic_parameters: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    output_file: str = "biochemical_model.xml"


def create_biochemical_network_sbml_model(arguments: dict, driver) -> dict:
    """Builds a real SBML Level 3 Version 2 model (`python-libsbml`) from a
    list of reactions (substrate/product stoichiometry) and writes it to
    `output_file`: one compartment, one species per unique reactant/product
    name, and one reaction per entry with a mass-action `KineticLaw`
    (`k_forward` from `kinetic_parameters[reaction_id]`, plus `k_reverse`
    when `reversible=True`)."""
    validated = CreateBiochemicalNetworkSbmlModelArgs.model_validate(arguments or {})
    output_file = ensure_safe_relative_path(validated.output_file)

    script_body = _dedent(
        """
        import json
        import libsbml

        reaction_network = _args["reaction_network"]
        kinetic_parameters = _args["kinetic_parameters"]
        output_file = _args["output_file"]

        document = libsbml.SBMLDocument(3, 2)
        model = document.createModel("biochemical_network")
        model.setTimeUnits("second")
        model.setExtentUnits("mole")
        model.setSubstanceUnits("mole")

        compartment = model.createCompartment()
        compartment.setId("cell")
        compartment.setConstant(True)
        compartment.setSize(1.0)
        compartment.setSpatialDimensions(3)

        species_ids = []
        for rxn in reaction_network:
            for sid in list(rxn["substrates"]) + list(rxn["products"]):
                if sid not in species_ids:
                    species_ids.append(sid)

        for sid in species_ids:
            sp = model.createSpecies()
            sp.setId(sid)
            sp.setCompartment("cell")
            sp.setConstant(False)
            sp.setBoundaryCondition(False)
            sp.setHasOnlySubstanceUnits(False)
            sp.setInitialConcentration(1.0)

        for rxn in reaction_network:
            reaction = model.createReaction()
            reaction.setId(rxn["id"])
            reaction.setReversible(bool(rxn["reversible"]))
            reaction.setFast(False)

            for sid, stoich in rxn["substrates"].items():
                ref = reaction.createReactant()
                ref.setSpecies(sid)
                ref.setStoichiometry(float(stoich))
                ref.setConstant(True)
            for sid, stoich in rxn["products"].items():
                ref = reaction.createProduct()
                ref.setSpecies(sid)
                ref.setStoichiometry(float(stoich))
                ref.setConstant(True)

            params = kinetic_parameters.get(rxn["id"], {})
            kf_id = rxn["id"] + "_kf"
            substrate_terms = " * ".join([kf_id] + list(rxn["substrates"])) if rxn["substrates"] else kf_id
            formula = substrate_terms
            has_reverse = rxn["reversible"] and rxn["products"]
            if has_reverse:
                kr_id = rxn["id"] + "_kr"
                product_terms = " * ".join([kr_id] + list(rxn["products"]))
                formula = f"({substrate_terms}) - ({product_terms})"

            kinetic_law = reaction.createKineticLaw()
            kinetic_law.setMath(libsbml.parseL3Formula(formula))

            kf_param = kinetic_law.createLocalParameter()
            kf_param.setId(kf_id)
            kf_param.setValue(float(params.get("k_forward", 1.0)))
            if has_reverse:
                kr_param = kinetic_law.createLocalParameter()
                kr_param.setId(kr_id)
                kr_param.setValue(float(params.get("k_reverse", 0.0)))

        libsbml.writeSBMLToFile(document, output_file)

        result = {
            "output_file": output_file,
            "n_species": len(species_ids),
            "n_reactions": len(reaction_network),
            "species_ids": species_ids,
            "reaction_ids": [r["id"] for r in reaction_network],
            "sbml_level": 3,
            "sbml_version": 2,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "reaction_network": [r.model_dump() for r in validated.reaction_network],
        "kinetic_parameters": validated.kinetic_parameters,
        "output_file": output_file,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# optimize_codons_for_heterologous_expression
# ---------------------------------------------------------------------------


class OptimizeCodonsArgs(BaseModel):
    target_sequence: str
    host_codon_usage: Dict[str, float]

    @field_validator("target_sequence")
    @classmethod
    def _valid_cds(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("target_sequence must be non-empty")
        if len(cleaned) % 3 != 0:
            raise ValueError("target_sequence length must be a multiple of 3 (a complete CDS)")
        if not set(cleaned) <= set("ACGT"):
            raise ValueError("target_sequence must contain only A/C/G/T")
        return cleaned

    @field_validator("host_codon_usage")
    @classmethod
    def _non_empty_usage(cls, value: Dict[str, float]) -> Dict[str, float]:
        if not value:
            raise ValueError("host_codon_usage must be a non-empty mapping of codon -> usage weight")
        return {str(k).upper(): float(v) for k, v in value.items()}


def optimize_codons_for_heterologous_expression(arguments: dict, driver) -> dict:
    """Real codon-usage optimization: for each codon in `target_sequence`,
    replaces it with the synonymous codon (per the standard genetic code)
    with the highest weight in `host_codon_usage`, and reports the Codon
    Adaptation Index (CAI; Sharp & Li 1987 -- geometric mean of each
    codon's relative adaptiveness `w = usage(codon) / max usage among its
    synonyms`) of both the original and optimized sequence."""
    validated = OptimizeCodonsArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json
        import math
        from Bio.Data.CodonTable import unambiguous_dna_by_id

        target_sequence = _args["target_sequence"]
        host_codon_usage = _args["host_codon_usage"]

        standard_table = unambiguous_dna_by_id[1]
        codon_to_aa = dict(standard_table.forward_table)
        for stop in standard_table.stop_codons:
            codon_to_aa[stop] = "*"

        aa_to_codons = {}
        for codon, aa in codon_to_aa.items():
            aa_to_codons.setdefault(aa, []).append(codon)

        def best_codon_for(aa):
            candidates = [c for c in aa_to_codons.get(aa, []) if c in host_codon_usage]
            if not candidates:
                return None
            return max(candidates, key=lambda c: host_codon_usage[c])

        def relative_adaptiveness(codon):
            aa = codon_to_aa.get(codon)
            synonyms = [c for c in aa_to_codons.get(aa, []) if c in host_codon_usage]
            if not synonyms or codon not in host_codon_usage:
                return None
            max_usage = max(host_codon_usage[c] for c in synonyms)
            if max_usage <= 0:
                return None
            return host_codon_usage[codon] / max_usage

        original_codons = [target_sequence[i:i + 3] for i in range(0, len(target_sequence), 3)]
        optimized_codons = []
        substitutions = []
        for pos, codon in enumerate(original_codons):
            aa = codon_to_aa.get(codon, "X")
            replacement = best_codon_for(aa)
            if replacement is None:
                optimized_codons.append(codon)
                continue
            optimized_codons.append(replacement)
            if replacement != codon:
                substitutions.append({
                    "position": pos, "amino_acid": aa,
                    "original_codon": codon, "optimized_codon": replacement,
                })

        def cai(codons):
            weights = [relative_adaptiveness(c) for c in codons]
            weights = [w for w in weights if w is not None and w > 0]
            if not weights:
                return None
            return math.exp(sum(math.log(w) for w in weights) / len(weights))

        result = {
            "original_sequence": "".join(original_codons),
            "optimized_sequence": "".join(optimized_codons),
            "num_codons": len(original_codons),
            "num_substitutions": len(substitutions),
            "substitutions": substitutions,
            "original_cai": cai(original_codons),
            "optimized_cai": cai(optimized_codons),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "target_sequence": validated.target_sequence,
        "host_codon_usage": validated.host_codon_usage,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# simulate_gene_circuit_with_growth_feedback
# ---------------------------------------------------------------------------


class SimulateGeneCircuitWithGrowthFeedbackArgs(BaseModel):
    circuit_topology: List[List[float]]
    kinetic_params: Dict[str, Any]
    growth_params: Dict[str, Any]
    simulation_time: float = Field(default=100.0, gt=0)
    time_points: int = Field(default=1000, gt=1)

    @model_validator(mode="after")
    def _topology_is_square(self) -> "SimulateGeneCircuitWithGrowthFeedbackArgs":
        n = len(self.circuit_topology)
        if n == 0:
            raise ValueError("circuit_topology must not be empty")
        if any(len(row) != n for row in self.circuit_topology):
            raise ValueError("circuit_topology must be a square (n_genes x n_genes) matrix")
        return self


def simulate_gene_circuit_with_growth_feedback(arguments: dict, driver) -> dict:
    """Simulates a gene regulatory circuit (`circuit_topology[i][j]` = signed
    regulatory weight of gene j on gene i; positive = activation, negative =
    repression, via normalized Hill functions) coupled to a growth-feedback
    dilution term: the population growth rate `mu = mu_max / (1 +
    total_protein / burden_K)` decreases as total expressed protein
    ("burden") rises, and every species is diluted by that same `mu` in
    addition to its own degradation rate -- a simplified, documented version
    of resource-competition/growth-feedback gene-circuit models (e.g. Weisse
    et al. 2015), reusing the shared `_ode_integration_and_report` core."""
    validated = SimulateGeneCircuitWithGrowthFeedbackArgs.model_validate(arguments or {})

    script_body = "\n".join([
        _dedent(
            """
            import json
            import numpy as np
            from scipy.integrate import solve_ivp

            topology = _args["circuit_topology"]
            kinetic_params = _args["kinetic_params"]
            growth_params = _args["growth_params"]
            n = len(topology)

            basal = kinetic_params.get("basal_rates", [0.0] * n)
            maxr = kinetic_params.get("max_rates", [1.0] * n)
            deg = kinetic_params.get("degradation_rates", [0.1] * n)
            hill_n = float(kinetic_params.get("hill_n", 2.0))
            K = float(kinetic_params.get("K", 1.0))
            y0 = kinetic_params.get("initial_conditions", [0.0] * n)
            mu_max = float(growth_params.get("mu_max", 1.0))
            burden_K = float(growth_params.get("burden_K", 1000.0))

            time_span = (0.0, float(_args["simulation_time"]))
            time_points = int(_args["time_points"])
            method = "LSODA"
            """
        ),
        _dedent(
            """
            def _rhs(t, y, topology, basal, maxr, deg, hill_n, K, mu_max, burden_K):
                total = sum(max(v, 0.0) for v in y)
                mu = mu_max / (1.0 + total / burden_K) if burden_K else mu_max
                dydt = [0.0] * n
                for i in range(n):
                    weighted_sum = 0.0
                    weight_total = 0.0
                    for j in range(n):
                        w = topology[i][j]
                        if w == 0:
                            continue
                        yj = max(y[j], 0.0)
                        denom = K ** hill_n + yj ** hill_n
                        hill = (yj ** hill_n) / denom if denom else 0.0
                        if w > 0:
                            weighted_sum += abs(w) * hill
                        else:
                            weighted_sum += abs(w) * (1 - hill)
                        weight_total += abs(w)
                    regulation = weighted_sum / weight_total if weight_total > 0 else 1.0
                    production = basal[i] + maxr[i] * regulation
                    dydt[i] = production - (deg[i] + mu) * y[i]
                return dydt
            """
        ),
        _ode_integration_and_report(
            y0_expr="y0",
            rhs_args_expr="(topology, basal, maxr, deg, hill_n, K, mu_max, burden_K)",
            extra_fields_expr=(
                '{"final_growth_rate": '
                'mu_max / (1.0 + sum(max(v, 0.0) for v in _sol.y[:, -1]) / burden_K) '
                'if burden_K else mu_max}'
            ),
        ),
    ])

    args = {
        "circuit_topology": validated.circuit_topology,
        "kinetic_params": validated.kinetic_params,
        "growth_params": validated.growth_params,
        "simulation_time": validated.simulation_time,
        "time_points": validated.time_points,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# identify_fas_functional_domains
# ---------------------------------------------------------------------------

# Simplified, honestly-labeled regex motif screen for a subset of canonical
# Fatty Acid Synthase (FAS) catalytic domains -- NOT a Pfam/HMMER domain
# call, deliberately restricted to short catalytic-site consensus motifs
# that are widely documented, well-established signatures (the alpha/beta-
# hydrolase GxSxG serine-hydrolase motif, the SDR-family YxxxK motif, the
# Rossmann-fold GxGxxG NAD(P)-binding motif, and the GxDSL phosphopantetheine
# -attachment motif). Ketoacyl synthase (KS) and dehydratase (DH) domains are
# NOT attempted here -- no sufficiently reliable short consensus for those
# two is bundled, and fabricating one would be worse than omitting it.
_FAS_DOMAIN_MOTIFS = {
    "MAT_AT": {
        "regex": r"G.S.G",
        "description": (
            "Alpha/beta-hydrolase-fold catalytic-serine signature (GxSxG) "
            "characteristic of the malonyl/acetyltransferase (MAT/AT) domain."
        ),
    },
    "KR": {
        "regex": r"Y...K",
        "description": (
            "SDR (short-chain dehydrogenase/reductase) family catalytic "
            "Tyr-x-x-x-Lys signature characteristic of the ketoreductase (KR) domain."
        ),
    },
    "ER": {
        "regex": r"G.G..G",
        "description": (
            "Rossmann-fold NAD(P)-binding glycine-rich signature (GxGxxG) "
            "characteristic of the enoyl reductase (ER) domain."
        ),
    },
    "ACP": {
        "regex": r"G.DSL",
        "description": (
            "Phosphopantetheine-attachment serine signature (GxDSL) "
            "characteristic of the acyl carrier protein (ACP) domain."
        ),
    },
}


class IdentifyFasFunctionalDomainsArgs(BaseModel):
    sequence: str
    sequence_type: str = "protein"
    output_file: str = "fas_domains_report.txt"

    @field_validator("sequence")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("sequence must be non-empty")
        return value.strip().upper()

    @field_validator("sequence_type")
    @classmethod
    def _valid_type(cls, value: str) -> str:
        if value not in {"protein", "dna"}:
            raise ValueError("sequence_type must be 'protein' or 'dna'")
        return value


def identify_fas_functional_domains(arguments: dict, driver) -> dict:
    """Approximate, pattern-based screen for a subset of canonical Fatty
    Acid Synthase (FAS) catalytic domain signatures: the alpha/beta-
    hydrolase catalytic-serine motif (GxSxG -- malonyl/acetyltransferase and
    thioesterase share it), the SDR-family Tyr-x-x-x-Lys motif
    (ketoreductase), the Rossmann-fold NAD(P)-binding motif (GxGxxG, enoyl
    reductase), and the phosphopantetheine-attachment motif (GxDSL, acyl
    carrier protein). Because MAT/AT and TE share the same GxSxG signature,
    hits are disambiguated only by relative position (N-terminal 60% ->
    MAT/AT candidates, C-terminal 20% -> TE candidates, the rest
    unclassified). This is a SIMPLIFIED, regex-motif-based screen -- NOT a
    validated Pfam/HMMER domain call (ketoacyl-synthase and dehydratase
    motifs are intentionally not attempted, see `_FAS_DOMAIN_MOTIFS`);
    confirm any result with a real HMM-based domain scan before drawing a
    biological conclusion."""
    validated = IdentifyFasFunctionalDomainsArgs.model_validate(arguments or {})
    output_file = ensure_safe_relative_path(validated.output_file)

    script_body = _dedent(
        """
        import json
        import re
        from Bio.Seq import Seq

        sequence = _args["sequence"]
        sequence_type = _args["sequence_type"]
        output_file = _args["output_file"]
        motifs = _args["fas_domain_motifs"]

        protein = str(Seq(sequence).translate(to_stop=True)) if sequence_type == "dna" else sequence
        n = len(protein)

        hits = {
            name: [
                {"position": m.start(), "matched_sequence": m.group(0)}
                for m in re.finditer(spec["regex"], protein)
            ]
            for name, spec in motifs.items()
        }

        gxsxg_hits = hits.get("MAT_AT", [])
        mat_candidates = [h for h in gxsxg_hits if h["position"] < 0.6 * n]
        te_candidates = [h for h in gxsxg_hits if h["position"] >= 0.8 * n]
        classified_positions = {h["position"] for h in mat_candidates + te_candidates}
        unclassified_gxsxg = [h for h in gxsxg_hits if h["position"] not in classified_positions]

        domains_found = {
            "MAT_AT_candidates": mat_candidates,
            "TE_candidates": te_candidates,
            "unclassified_GxSxG_hits": unclassified_gxsxg,
            "KR_candidates": hits.get("KR", []),
            "ER_candidates": hits.get("ER", []),
            "ACP_candidates": hits.get("ACP", []),
        }

        lines = [f"FAS functional domain report (simplified pattern screen, protein length {n} aa)"]
        for domain_name, entries in domains_found.items():
            lines.append(f"{domain_name}: {len(entries)} hit(s)")
            for entry in entries:
                lines.append(f"  position {entry['position']}: {entry['matched_sequence']}")
        with open(output_file, "w", encoding="utf-8") as fh:
            fh.write("\\n".join(lines))

        result = {
            "output_file": output_file,
            "protein_length": n,
            "domains_found": domains_found,
            "disclaimer": (
                "Simplified regex-motif-based screen, not a validated Pfam/HMMER "
                "domain call -- confirm with a real HMM-based scan before drawing "
                "biological conclusions."
            ),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "sequence": validated.sequence,
        "sequence_type": validated.sequence_type,
        "output_file": output_file,
        "fas_domain_motifs": _FAS_DOMAIN_MOTIFS,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# perform_flux_balance_analysis
# ---------------------------------------------------------------------------


class PerformFluxBalanceAnalysisArgs(BaseModel):
    model_file: str
    constraints: Optional[Dict[str, List[float]]] = None
    objective_reaction: Optional[str] = None
    output_file: str = "fba_results.csv"

    @field_validator("constraints")
    @classmethod
    def _valid_constraints(
        cls, value: Optional[Dict[str, List[float]]]
    ) -> Optional[Dict[str, List[float]]]:
        if value is None:
            return value
        for rxn_id, bounds in value.items():
            if len(bounds) != 2:
                raise ValueError(f"constraints[{rxn_id!r}] must be a [lower_bound, upper_bound] pair")
        return value


def perform_flux_balance_analysis(arguments: dict, driver) -> dict:
    """Real Flux Balance Analysis via `cobra`: loads a metabolic model from
    `model_file` (SBML `.xml`/`.sbml`, COBRA JSON `.json`, or MATLAB `.mat`,
    detected by extension), optionally overrides reaction bounds from
    `constraints` (`{reaction_id: [lower_bound, upper_bound]}`) and the
    objective reaction, solves the linear program (`model.optimize()`), and
    writes every reaction's flux to `output_file`."""
    validated = PerformFluxBalanceAnalysisArgs.model_validate(arguments or {})
    model_file = ensure_safe_relative_path(validated.model_file)
    output_file = ensure_safe_relative_path(validated.output_file)

    script_body = _dedent(
        """
        import csv
        import json
        import cobra

        model_file = _args["model_file"]
        constraints = _args.get("constraints") or {}
        objective_reaction = _args.get("objective_reaction")
        output_file = _args["output_file"]

        lower_name = model_file.lower()
        if lower_name.endswith(".json"):
            model = cobra.io.load_json_model(model_file)
        elif lower_name.endswith(".mat"):
            model = cobra.io.load_matlab_model(model_file)
        else:
            model = cobra.io.read_sbml_model(model_file)

        for rxn_id, bounds in constraints.items():
            reaction = model.reactions.get_by_id(rxn_id)
            reaction.lower_bound = float(bounds[0])
            reaction.upper_bound = float(bounds[1])

        if objective_reaction:
            model.objective = objective_reaction

        solution = model.optimize()

        with open(output_file, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["reaction_id", "flux"])
            for rxn_id, flux in solution.fluxes.items():
                writer.writerow([rxn_id, flux])

        result = {
            "output_file": output_file,
            "status": solution.status,
            "objective_value": (
                float(solution.objective_value) if solution.objective_value is not None else None
            ),
            "objective_reaction": objective_reaction or str(model.objective.expression),
            "n_reactions": len(model.reactions),
            "n_metabolites": len(model.metabolites),
            "fluxes": {rxn_id: float(flux) for rxn_id, flux in solution.fluxes.items()},
        }
        print(json.dumps(result))
        """
    )
    args = {
        "model_file": model_file,
        "constraints": validated.constraints,
        "objective_reaction": validated.objective_reaction,
        "output_file": output_file,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# model_protein_dimerization_network
# ---------------------------------------------------------------------------


class ModelProteinDimerizationNetworkArgs(BaseModel):
    monomer_concentrations: Dict[str, float]
    dimerization_affinities: Dict[str, float]
    network_topology: List[List[str]]

    @field_validator("monomer_concentrations")
    @classmethod
    def _non_empty_conc(cls, value: Dict[str, float]) -> Dict[str, float]:
        if not value:
            raise ValueError(
                "monomer_concentrations must be a non-empty mapping of protein -> total "
                "concentration"
            )
        return value

    @field_validator("network_topology")
    @classmethod
    def _valid_pairs(cls, value: List[List[str]]) -> List[List[str]]:
        if not value:
            raise ValueError("network_topology must list at least one candidate dimer pair")
        for pair in value:
            if len(pair) != 2:
                raise ValueError(f"each network_topology entry must be a [monomer_a, monomer_b] pair, got {pair!r}")
        return value


def model_protein_dimerization_network(arguments: dict, driver) -> dict:
    """Solves the real coupled mass-action equilibrium for a network of
    possible protein dimers: for each candidate pair (A, B) in
    `network_topology` with dissociation constant `Kd = [A_free][B_free] /
    [AB]` (from `dimerization_affinities`, keyed `"A-B"` or `"B-A"`), and
    each monomer's conservation law `total_A = free_A + sum of dimers
    containing A` (a homodimer AA contributes `2 * [AA]`), solves the
    resulting nonlinear system for free-monomer concentrations via
    `scipy.optimize.least_squares`, then derives every dimer's equilibrium
    concentration and each monomer's fraction dimerized."""
    validated = ModelProteinDimerizationNetworkArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json
        import numpy as np
        from scipy.optimize import least_squares

        totals = _args["monomer_concentrations"]
        affinities = _args["dimerization_affinities"]
        topology = _args["network_topology"]

        monomers = list(totals)
        idx = {m: i for i, m in enumerate(monomers)}

        pairs = []
        for a, b in topology:
            if a not in idx or b not in idx:
                raise ValueError(f"network_topology pair ({a!r}, {b!r}) references an unknown monomer")
            key = f"{a}-{b}" if f"{a}-{b}" in affinities else f"{b}-{a}"
            if key not in affinities:
                raise ValueError(f"dimerization_affinities is missing a Kd for pair ({a!r}, {b!r})")
            pairs.append((a, b, float(affinities[key])))

        total_vec = np.array([totals[m] for m in monomers], dtype=float)

        def residuals(x_free):
            x_free = np.clip(x_free, 1e-12, None)
            consumed = np.zeros(len(monomers))
            for a, b, kd in pairs:
                d = x_free[idx[a]] * x_free[idx[b]] / kd
                if a == b:
                    consumed[idx[a]] += 2 * d
                else:
                    consumed[idx[a]] += d
                    consumed[idx[b]] += d
            return (x_free + consumed) - total_vec

        x0 = total_vec.copy()
        bounds = (np.zeros(len(monomers)), total_vec + 1e-9)
        solution = least_squares(residuals, x0, bounds=bounds)
        free = np.clip(solution.x, 0.0, None)

        dimer_results = []
        dimer_totals = {m: 0.0 for m in monomers}
        for a, b, kd in pairs:
            d = free[idx[a]] * free[idx[b]] / kd
            dimer_results.append({
                "monomer_a": a, "monomer_b": b, "kd": kd, "equilibrium_concentration": float(d),
            })
            if a == b:
                dimer_totals[a] += 2 * d
            else:
                dimer_totals[a] += d
                dimer_totals[b] += d

        free_concentrations = {m: float(free[idx[m]]) for m in monomers}
        fraction_dimerized = {
            m: float(dimer_totals[m] / totals[m]) if totals[m] > 0 else 0.0 for m in monomers
        }

        result = {
            "converged": bool(solution.success),
            "free_monomer_concentrations": free_concentrations,
            "dimers": dimer_results,
            "fraction_dimerized": fraction_dimerized,
            "residual_norm": float(np.linalg.norm(solution.fun)),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "monomer_concentrations": validated.monomer_concentrations,
        "dimerization_affinities": validated.dimerization_affinities,
        "network_topology": validated.network_topology,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# simulate_metabolic_network_perturbation
# ---------------------------------------------------------------------------


class SimulateMetabolicNetworkPerturbationArgs(BaseModel):
    model_file: str
    initial_concentrations: Dict[str, float]
    perturbation_params: Dict[str, Any] = Field(default_factory=dict)
    simulation_time: float = Field(default=100.0, gt=0)
    time_points: int = Field(default=1000, gt=1)

    @field_validator("initial_concentrations")
    @classmethod
    def _non_empty_concentrations(cls, value: Dict[str, float]) -> Dict[str, float]:
        if not value:
            raise ValueError(
                "initial_concentrations must be a non-empty mapping of species -> concentration"
            )
        return value


def simulate_metabolic_network_perturbation(arguments: dict, driver) -> dict:
    """Real mass-action kinetic simulation of a metabolic reaction network
    loaded from `model_file` (a JSON file: `{"reactions": [{"substrates":
    {sp: stoich}, "products": {sp: stoich}, "k_forward": kf, "k_reverse":
    kr}, ...]}`), integrated once over `[0, simulation_time]` with a
    right-hand side that switches from baseline to perturbed reaction rates
    at `perturbation_params["perturbation_time"]` (default 0, i.e.
    perturbed from the start). The perturbation itself is modeled as a
    kinetic-parameter change -- `perturbation_params["rate_multipliers"]`
    (`{"<reaction_index>": {"k_forward": m, "k_reverse": m}}`, e.g. modeling
    an enzyme inhibitor or knockout) -- not an instantaneous concentration
    jump; the adaptive integrator handles the resulting rate-function
    discontinuity directly (no explicit step-size hint), adequate for
    typical smooth-kinetics perturbations. Reuses the shared
    `_ode_integration_and_report` core."""
    validated = SimulateMetabolicNetworkPerturbationArgs.model_validate(arguments or {})
    model_file = ensure_safe_relative_path(validated.model_file)

    script_body = "\n".join([
        _dedent(
            """
            import json
            import numpy as np
            from scipy.integrate import solve_ivp

            with open(_args["model_file"], encoding="utf-8") as fh:
                model = json.load(fh)
            reactions_spec = model["reactions"]
            initial_concentrations = _args["initial_concentrations"]
            perturbation_params = _args["perturbation_params"]

            species = list(initial_concentrations)
            for rxn in reactions_spec:
                for sp in list(rxn.get("substrates", {})) + list(rxn.get("products", {})):
                    if sp not in species:
                        species.append(sp)
            species_index = {sp: i for i, sp in enumerate(species)}
            y0 = [float(initial_concentrations.get(sp, 0.0)) for sp in species]

            def build_reactions(rate_multipliers):
                built = []
                for idx, rxn in enumerate(reactions_spec):
                    mult = rate_multipliers.get(str(idx), {})
                    kf = float(rxn.get("k_forward", 0.0)) * float(mult.get("k_forward", 1.0))
                    kr = float(rxn.get("k_reverse", 0.0)) * float(mult.get("k_reverse", 1.0))
                    built.append((rxn.get("substrates", {}), rxn.get("products", {}), kf, kr))
                return built

            perturbation_time = max(0.0, min(
                float(perturbation_params.get("perturbation_time", 0.0)),
                float(_args["simulation_time"]),
            ))
            baseline_reactions = build_reactions({})
            perturbed_reactions = build_reactions(perturbation_params.get("rate_multipliers", {}))

            time_span = (0.0, float(_args["simulation_time"]))
            time_points = int(_args["time_points"])
            method = "LSODA"
            """
        ),
        _dedent(
            """
            def _rhs(t, y, baseline_reactions, perturbed_reactions, perturbation_time, species_index):
                reactions = perturbed_reactions if t >= perturbation_time else baseline_reactions
                dydt = [0.0] * len(y)
                for subs, prods, kf, kr in reactions:
                    rate_f = kf
                    for sp, coeff in subs.items():
                        rate_f *= max(y[species_index[sp]], 0.0) ** coeff
                    rate_r = kr
                    for sp, coeff in prods.items():
                        rate_r *= max(y[species_index[sp]], 0.0) ** coeff
                    net = rate_f - rate_r
                    for sp, coeff in subs.items():
                        dydt[species_index[sp]] -= coeff * net
                    for sp, coeff in prods.items():
                        dydt[species_index[sp]] += coeff * net
                return dydt
            """
        ),
        _ode_integration_and_report(
            y0_expr="y0",
            rhs_args_expr=(
                "(baseline_reactions, perturbed_reactions, perturbation_time, species_index)"
            ),
            extra_fields_expr=(
                '{"species_names": species, "perturbation_time": perturbation_time, '
                '"final_concentrations": {sp: _sol.y[i][-1] for i, sp in enumerate(species)}}'
            ),
        ),
    ])
    args = {
        "model_file": model_file,
        "initial_concentrations": validated.initial_concentrations,
        "perturbation_params": validated.perturbation_params,
        "simulation_time": validated.simulation_time,
        "time_points": validated.time_points,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# simulate_protein_signaling_network
# ---------------------------------------------------------------------------


class SimulateProteinSignalingNetworkArgs(BaseModel):
    network_structure: Dict[str, Any]
    reaction_params: Dict[str, Any] = Field(default_factory=dict)
    species_params: Dict[str, Any] = Field(default_factory=dict)
    simulation_time: float = Field(default=100.0, gt=0)
    time_points: int = Field(default=1000, gt=1)

    @model_validator(mode="after")
    def _has_species(self) -> "SimulateProteinSignalingNetworkArgs":
        if not self.network_structure.get("species"):
            raise ValueError("network_structure must include a non-empty 'species' list")
        return self


def simulate_protein_signaling_network(arguments: dict, driver) -> dict:
    """Simulates a protein signaling network as a logic-based ODE model with
    normalized Hill functions (simplified version of the Wittmann et al.
    2009 formalism): each edge in `network_structure["edges"]` (`source`,
    `target`, `type` in `{"activation", "inhibition"}`) contributes a
    normalized Hill term `h = y_source^n * (EC50^n + 1) / (EC50^n +
    y_source^n)` (so `h(0)=0`, `h(1)=1`), combined per target species via a
    probabilistic-OR across activators and an AND-NOT across inhibitors into
    `Omega`, then integrated as `tau * dy/dt = Omega(y) - y`. Species with no
    incoming edges are held at their `species_params` initial value (treated
    as external stimuli/inputs). Reuses the shared
    `_ode_integration_and_report` core."""
    validated = SimulateProteinSignalingNetworkArgs.model_validate(arguments or {})

    script_body = "\n".join([
        _dedent(
            """
            import json
            import numpy as np
            from scipy.integrate import solve_ivp

            network_structure = _args["network_structure"]
            reaction_params = _args["reaction_params"]
            species_params = _args["species_params"]

            species = list(network_structure["species"])
            species_index = {sp: i for i, sp in enumerate(species)}
            edges = network_structure.get("edges", [])

            incoming = {i: [] for i in range(len(species))}
            for edge in edges:
                source = edge["source"]
                target = edge["target"]
                edge_type = edge.get("type", "activation")
                if source not in species_index or target not in species_index:
                    continue
                key = source + "->" + target
                params = reaction_params.get(key, {})
                n_hill = float(params.get("n", 2.0))
                ec50 = float(params.get("EC50", 0.5))
                incoming[species_index[target]].append((species_index[source], edge_type, n_hill, ec50))

            has_incoming = [len(incoming[i]) > 0 for i in range(len(species))]
            tau = [float(species_params.get(sp, {}).get("tau", 1.0)) for sp in species]
            y0 = [float(species_params.get(sp, {}).get("initial_value", 0.0)) for sp in species]

            time_span = (0.0, float(_args["simulation_time"]))
            time_points = int(_args["time_points"])
            method = "LSODA"
            """
        ),
        _dedent(
            """
            def _rhs(t, y, incoming, tau, has_incoming):
                dydt = [0.0] * len(y)
                for i in range(len(y)):
                    if not has_incoming[i]:
                        dydt[i] = 0.0
                        continue
                    act_term = 1.0
                    inhib_term = 1.0
                    any_act = False
                    any_inhib = False
                    for source_idx, edge_type, n_hill, ec50 in incoming[i]:
                        ys = max(y[source_idx], 0.0)
                        denom = ec50 ** n_hill + ys ** n_hill
                        h = ys ** n_hill * (ec50 ** n_hill + 1) / denom if denom else 0.0
                        if edge_type == "activation":
                            act_term *= (1 - h)
                            any_act = True
                        else:
                            inhib_term *= (1 - h)
                            any_inhib = True
                    activator_part = (1 - act_term) if any_act else 1.0
                    inhibitor_part = inhib_term if any_inhib else 1.0
                    omega = activator_part * inhibitor_part
                    dydt[i] = (omega - y[i]) / tau[i]
                return dydt
            """
        ),
        _ode_integration_and_report(
            y0_expr="y0",
            rhs_args_expr="(incoming, tau, has_incoming)",
            extra_fields_expr='{"species_names": species}',
        ),
    ])
    args = {
        "network_structure": validated.network_structure,
        "reaction_params": validated.reaction_params,
        "species_params": validated.species_params,
        "simulation_time": validated.simulation_time,
        "time_points": validated.time_points,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# compare_protein_structures
# ---------------------------------------------------------------------------


class CompareProteinStructuresArgs(BaseModel):
    pdb_file1: str
    pdb_file2: str
    chain_id1: str = "A"
    chain_id2: str = "A"
    output_prefix: str = "protein_comparison"


def compare_protein_structures(arguments: dict, driver) -> dict:
    """Structural comparison of two PDB structures via Biopython's
    `Bio.PDB.Superimposer` (Kabsch algorithm): extracts C-alpha coordinates
    for the specified chain from each structure, superimposes the first
    `min(len(chain1), len(chain2))` C-alpha atoms of each onto each other
    (a simple index-aligned comparison -- NOT a full sequence-independent
    structural aligner like TM-align/DALI, documented as such), writes the
    superimposed structure, and reports the resulting RMSD."""
    validated = CompareProteinStructuresArgs.model_validate(arguments or {})
    pdb_file1 = ensure_safe_relative_path(validated.pdb_file1)
    pdb_file2 = ensure_safe_relative_path(validated.pdb_file2)
    output_prefix = ensure_safe_relative_path(validated.output_prefix)

    script_body = _dedent(
        """
        import json
        from Bio.PDB import PDBIO, PDBParser, Superimposer

        pdb_file1 = _args["pdb_file1"]
        pdb_file2 = _args["pdb_file2"]
        chain_id1 = _args["chain_id1"]
        chain_id2 = _args["chain_id2"]
        output_prefix = _args["output_prefix"]

        parser = PDBParser(QUIET=True)
        structure1 = parser.get_structure("s1", pdb_file1)
        structure2 = parser.get_structure("s2", pdb_file2)

        def ca_atoms(structure, chain_id):
            chain = structure[0][chain_id]
            return [residue["CA"] for residue in chain if "CA" in residue]

        atoms1 = ca_atoms(structure1, chain_id1)
        atoms2 = ca_atoms(structure2, chain_id2)
        if not atoms1 or not atoms2:
            raise ValueError("could not find any C-alpha atoms in the requested chain(s)")

        n_compared = min(len(atoms1), len(atoms2))
        fixed = atoms1[:n_compared]
        moving = atoms2[:n_compared]

        superimposer = Superimposer()
        superimposer.set_atoms(fixed, moving)
        superimposer.apply(structure2[0][chain_id2])

        aligned_path = f"{output_prefix}_aligned.pdb"
        io_writer = PDBIO()
        io_writer.set_structure(structure2)
        io_writer.save(aligned_path)

        result = {
            "output_prefix": output_prefix,
            "aligned_structure_file": aligned_path,
            "rmsd": float(superimposer.rms),
            "n_residues_compared": n_compared,
            "n_residues_chain1": len(atoms1),
            "n_residues_chain2": len(atoms2),
            "chain_id1": chain_id1,
            "chain_id2": chain_id2,
            "comparison_method": (
                "index-aligned C-alpha Kabsch superposition over the first "
                f"{n_compared} residues -- not a sequence-independent structural aligner"
            ),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "pdb_file1": pdb_file1,
        "pdb_file2": pdb_file2,
        "chain_id1": validated.chain_id1,
        "chain_id2": validated.chain_id2,
        "output_prefix": output_prefix,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# simulate_renin_angiotensin_system_dynamics
# ---------------------------------------------------------------------------

_RAS_SPECIES = ["Renin", "AGT", "AngI", "AngII"]


class SimulateReninAngiotensinSystemDynamicsArgs(BaseModel):
    initial_concentrations: Dict[str, float]
    rate_constants: Dict[str, float] = Field(default_factory=dict)
    feedback_params: Dict[str, Any] = Field(default_factory=dict)
    simulation_time: float = Field(default=48.0, gt=0)
    time_points: int = Field(default=100, gt=1)

    @field_validator("initial_concentrations")
    @classmethod
    def _has_ras_species(cls, value: Dict[str, float]) -> Dict[str, float]:
        missing = [sp for sp in _RAS_SPECIES if sp not in value]
        if missing:
            raise ValueError(f"initial_concentrations must include {_RAS_SPECIES}; missing {missing}")
        return value


def simulate_renin_angiotensin_system_dynamics(arguments: dict, driver) -> dict:
    """Simplified, real compartmental ODE model of the renin-angiotensin
    system (RAS) negative-feedback cascade over four species (`Renin`,
    `AGT` = angiotensinogen, `AngI`, `AngII`): `AGT` is cleaved by `Renin`
    into `AngI` (rate `k1`), `AngI` is converted to `AngII` by lumped ACE
    activity (rate `k2`), `AngII` is cleared at rate `k3`, and `AngII`
    inhibits `Renin` synthesis via a Hill-function negative-feedback term
    (`feedback_params`) -- the well-documented physiological negative
    feedback of angiotensin II on renin release. Reuses the shared
    `_ode_integration_and_report` core."""
    validated = SimulateReninAngiotensinSystemDynamicsArgs.model_validate(arguments or {})

    script_body = "\n".join([
        _dedent(
            """
            import json
            import numpy as np
            from scipy.integrate import solve_ivp

            initial_concentrations = _args["initial_concentrations"]
            rate_constants = _args["rate_constants"]
            feedback_params = _args["feedback_params"]

            species = ["Renin", "AGT", "AngI", "AngII"]
            y0 = [float(initial_concentrations[sp]) for sp in species]
            k = {
                "k_renin_synthesis": float(rate_constants.get("k_renin_synthesis", 1.0)),
                "k_renin_degradation": float(rate_constants.get("k_renin_degradation", 0.1)),
                "k1": float(rate_constants.get("k1", 0.01)),
                "k2": float(rate_constants.get("k2", 0.5)),
                "k3": float(rate_constants.get("k3", 0.3)),
                "k_agt_synthesis": float(rate_constants.get("k_agt_synthesis", 1.0)),
                "K_feedback": float(feedback_params.get("K_feedback", 1.0)),
                "hill_n": float(feedback_params.get("hill_n", 2.0)),
                "feedback_strength": float(feedback_params.get("feedback_strength", 1.0)),
            }

            time_span = (0.0, float(_args["simulation_time"]))
            time_points = int(_args["time_points"])
            method = "LSODA"
            """
        ),
        _dedent(
            """
            def _rhs(t, y, k):
                renin, agt, ang1, ang2 = y
                if k["K_feedback"]:
                    inhibition = 1.0 / (
                        1.0 + k["feedback_strength"] * (max(ang2, 0.0) / k["K_feedback"]) ** k["hill_n"]
                    )
                else:
                    inhibition = 1.0
                d_renin = k["k_renin_synthesis"] * inhibition - k["k_renin_degradation"] * renin
                d_agt = k["k_agt_synthesis"] - k["k1"] * renin * agt
                d_ang1 = k["k1"] * renin * agt - k["k2"] * ang1
                d_ang2 = k["k2"] * ang1 - k["k3"] * ang2
                return [d_renin, d_agt, d_ang1, d_ang2]
            """
        ),
        _ode_integration_and_report(
            y0_expr="y0",
            rhs_args_expr="(k,)",
            extra_fields_expr='{"species_names": species}',
        ),
    ])
    args = {
        "initial_concentrations": validated.initial_concentrations,
        "rate_constants": validated.rate_constants,
        "feedback_params": validated.feedback_params,
        "simulation_time": validated.simulation_time,
        "time_points": validated.time_points,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# simulate_whole_cell_ode_model
# ---------------------------------------------------------------------------

_SUPPORTED_ODE_FUNCTIONS = {"mass_action_chain", "linear_decay", "logistic_growth"}
_SUPPORTED_ODE_METHODS = {"RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA"}


class SimulateWholeCellOdeModelArgs(BaseModel):
    initial_conditions: List[float] = Field(min_length=1)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    ode_function: Optional[str] = None
    time_span: Tuple[float, float] = (0.0, 100.0)
    time_points: int = Field(default=1000, gt=1)
    method: str = "LSODA"

    @field_validator("ode_function")
    @classmethod
    def _valid_ode_function(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _SUPPORTED_ODE_FUNCTIONS:
            raise ValueError(
                f"ode_function must be one of {sorted(_SUPPORTED_ODE_FUNCTIONS)} or omitted "
                "for the default example model"
            )
        return value

    @field_validator("method")
    @classmethod
    def _valid_method(cls, value: str) -> str:
        if value not in _SUPPORTED_ODE_METHODS:
            raise ValueError(f"method must be one of {sorted(_SUPPORTED_ODE_METHODS)}")
        return value

    @model_validator(mode="after")
    def _time_span_is_forward(self) -> "SimulateWholeCellOdeModelArgs":
        if self.time_span[1] <= self.time_span[0]:
            raise ValueError("time_span end must be greater than time_span start")
        return self


def simulate_whole_cell_ode_model(arguments: dict, driver) -> dict:
    """Generic `scipy.integrate.solve_ivp` ODE-integration building block --
    the shared numeric core (`_ode_integration_and_report`) that
    `simulate_gene_circuit_with_growth_feedback`,
    `simulate_metabolic_network_perturbation`,
    `simulate_protein_signaling_network`, and
    `simulate_renin_angiotensin_system_dynamics` above are all specific,
    hand-written parameterizations of. `ode_function` selects one of a
    small WHITELISTED set of named example right-hand-side systems (never
    LLM-supplied Python source -- there is no `eval` of caller input
    anywhere in this module): `"mass_action_chain"` (default -- a
    sequential unimolecular conversion chain `y0 -> y1 -> ... -> y(n-1)`, a
    generic whole-cell-style multi-compartment cascade;
    `parameters["rate_constants"]`, one per species), `"linear_decay"`
    (independent first-order decay per species; same parameter), or
    `"logistic_growth"` (independent logistic growth per species;
    `parameters["growth_rates"]`/`parameters["capacities"]`)."""
    validated = SimulateWholeCellOdeModelArgs.model_validate(arguments or {})
    ode_function = validated.ode_function or "mass_action_chain"

    if ode_function == "mass_action_chain":
        rhs_body = _dedent(
            """
            def _rhs(t, y, parameters):
                n = len(y)
                k = parameters.get("rate_constants", [1.0] * n)
                if len(k) != n:
                    raise ValueError("parameters['rate_constants'] must have one entry per species")
                dydt = [0.0] * n
                inflow = 0.0
                for i in range(n):
                    outflow = k[i] * y[i]
                    dydt[i] = inflow - outflow
                    inflow = outflow
                return dydt
            """
        )
    elif ode_function == "linear_decay":
        rhs_body = _dedent(
            """
            def _rhs(t, y, parameters):
                n = len(y)
                k = parameters.get("rate_constants", [1.0] * n)
                if len(k) != n:
                    raise ValueError("parameters['rate_constants'] must have one entry per species")
                return [-k[i] * y[i] for i in range(n)]
            """
        )
    else:  # logistic_growth
        rhs_body = _dedent(
            """
            def _rhs(t, y, parameters):
                n = len(y)
                r = parameters.get("growth_rates", [1.0] * n)
                K = parameters.get("capacities", [1.0] * n)
                if len(r) != n or len(K) != n:
                    raise ValueError(
                        "parameters['growth_rates']/['capacities'] must have one entry per species"
                    )
                return [r[i] * y[i] * (1 - y[i] / K[i]) if K[i] else 0.0 for i in range(n)]
            """
        )

    script_body = "\n".join([
        _dedent(
            """
            import json
            import numpy as np
            from scipy.integrate import solve_ivp

            y0 = list(_args["initial_conditions"])
            parameters = _args["parameters"]
            time_span = tuple(_args["time_span"])
            time_points = int(_args["time_points"])
            method = _args["method"]
            """
        ),
        rhs_body,
        _ode_integration_and_report(y0_expr="y0", rhs_args_expr="(parameters,)"),
    ])

    args = {
        "initial_conditions": validated.initial_conditions,
        "parameters": validated.parameters,
        "time_span": list(validated.time_span),
        "time_points": validated.time_points,
        "method": validated.method,
        "ode_function": ode_function,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_in_vitro_drug_release_kinetics
# ---------------------------------------------------------------------------


class AnalyzeInVitroDrugReleaseKineticsArgs(BaseModel):
    time_points: List[float] = Field(min_length=3)
    concentration_data: List[float] = Field(min_length=3)
    drug_name: str = "Drug"
    total_drug_loaded: Optional[float] = None
    output_dir: str = "./"

    @model_validator(mode="after")
    def _lengths_match(self) -> "AnalyzeInVitroDrugReleaseKineticsArgs":
        if len(self.time_points) != len(self.concentration_data):
            raise ValueError("time_points and concentration_data must have the same length")
        return self


def analyze_in_vitro_drug_release_kinetics(arguments: dict, driver) -> dict:
    """Fits three real, standard drug-release kinetic models to
    `time_points`/`concentration_data` via `scipy.optimize.curve_fit`:
    zero-order (`Q = Q0 + k0*t`), first-order (`Q = Qmax*(1-exp(-k1*t))`),
    and the Higuchi square-root-of-time model (`Q = kH*sqrt(t)`). Reports
    each model's fitted parameters and R-squared, and identifies the
    best-fitting model by R-squared."""
    validated = AnalyzeInVitroDrugReleaseKineticsArgs.model_validate(arguments or {})
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os
        import numpy as np
        from scipy.optimize import curve_fit

        t = np.asarray(_args["time_points"], dtype=float)
        q = np.asarray(_args["concentration_data"], dtype=float)
        drug_name = _args["drug_name"]
        total_drug_loaded = _args.get("total_drug_loaded")
        output_dir = _args["output_dir"]
        os.makedirs(output_dir, exist_ok=True)

        def zero_order(t, q0, k0):
            return q0 + k0 * t

        def first_order(t, qmax, k1):
            return qmax * (1 - np.exp(-k1 * t))

        def higuchi(t, kh):
            return kh * np.sqrt(np.clip(t, 0, None))

        qmax_guess = total_drug_loaded if total_drug_loaded else float(np.max(q)) * 1.2 + 1e-6

        models = {
            "zero_order": (zero_order, [float(q[0]), 1.0]),
            "first_order": (first_order, [qmax_guess, 0.1]),
            "higuchi": (higuchi, [1.0]),
        }

        fits = {}
        for name, (func, p0) in models.items():
            try:
                popt, _ = curve_fit(func, t, q, p0=p0, maxfev=10000)
                predicted = func(t, *popt)
                ss_res = float(np.sum((q - predicted) ** 2))
                ss_tot = float(np.sum((q - np.mean(q)) ** 2))
                r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else None
                fits[name] = {
                    "parameters": [float(p) for p in popt],
                    "r_squared": r_squared,
                    "converged": True,
                }
            except Exception as exc:
                fits[name] = {
                    "parameters": None, "r_squared": None, "converged": False, "error": str(exc),
                }

        ranked = [name for name, fit in fits.items() if fit["r_squared"] is not None]
        best_model = max(ranked, key=lambda name: fits[name]["r_squared"]) if ranked else None

        result = {
            "drug_name": drug_name,
            "output_dir": output_dir,
            "fits": fits,
            "best_model": best_model,
            "parameter_names": {
                "zero_order": ["Q0", "k0"],
                "first_order": ["Qmax", "k1"],
                "higuchi": ["kH"],
            },
        }
        out_path = os.path.join(output_dir, f"{drug_name}_release_kinetics.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh)
        result["output_file"] = out_path
        print(json.dumps(result))
        """
    )
    args = {
        "time_points": validated.time_points,
        "concentration_data": validated.concentration_data,
        "drug_name": validated.drug_name,
        "total_drug_loaded": validated.total_drug_loaded,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_TOOL_HANDLERS = {
    "engineer_bacterial_genome_for_therapeutic_delivery": engineer_bacterial_genome_for_therapeutic_delivery,
    "analyze_barcode_sequencing_data": analyze_barcode_sequencing_data,
    "analyze_bifurcation_diagram": analyze_bifurcation_diagram,
    "create_biochemical_network_sbml_model": create_biochemical_network_sbml_model,
    "optimize_codons_for_heterologous_expression": optimize_codons_for_heterologous_expression,
    "simulate_gene_circuit_with_growth_feedback": simulate_gene_circuit_with_growth_feedback,
    "identify_fas_functional_domains": identify_fas_functional_domains,
    "perform_flux_balance_analysis": perform_flux_balance_analysis,
    "model_protein_dimerization_network": model_protein_dimerization_network,
    "simulate_metabolic_network_perturbation": simulate_metabolic_network_perturbation,
    "simulate_protein_signaling_network": simulate_protein_signaling_network,
    "compare_protein_structures": compare_protein_structures,
    "simulate_renin_angiotensin_system_dynamics": simulate_renin_angiotensin_system_dynamics,
    "simulate_whole_cell_ode_model": simulate_whole_cell_ode_model,
    "analyze_in_vitro_drug_release_kinetics": analyze_in_vitro_drug_release_kinetics,
}


def register_synthetic_systems_biology_tools(registry, driver) -> List[str]:
    """Registers every Synthetic biology & systems biology action tool into
    `registry`, each bound to the shared sandbox `driver`. Returns the list
    of registered tool names."""
    for name, handler in _TOOL_HANDLERS.items():
        registry.register_server(name, functools.partial(handler, driver=driver))
    return list(_TOOL_HANDLERS.keys())
