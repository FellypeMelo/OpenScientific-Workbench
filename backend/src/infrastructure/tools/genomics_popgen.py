"""Genomics & population genetics action tools (Fase 5).

Implements every tool listed under the "Categoria: Genomics & population
genetics" heading of `backend/docs/tools/action_tool_catalog.md`. Every tool
in this category is Tier A or Tier B (no Tier D entries here -- nothing in
this category needs a proprietary pretrained checkpoint or a GPU cluster) and
therefore runs its real scientific logic inside the sandbox via
`run_in_sandbox` (see `_sandbox_tool_base.py`'s module docstring for exactly
why -- LLM-influenced arguments never reach an in-process biopython/scipy/
msprime import in this trusted backend process).

Per-tool tiering (see `action_tool_catalog.md` for the authoritative source,
this is a recap, not a re-derivation):

- Tier A (deterministic real lib, no statistical model): `liftover_coordinates`
  (pyliftover), `analyze_cas9_mutation_outcomes` /
  `analyze_crispr_genome_editing` / `perform_crispr_cas9_genome_editing`
  (Biopython pairwise alignment + motif search -- the last one is explicitly
  documented as a computational guide-design QC *simulation*, not a wet-lab
  result), `simulate_demographic_history` (real `msprime` coalescent call),
  `identify_transcription_factor_binding_sites` (real PWM sliding-window scan
  against a small bundled reference set of published consensus motifs --
  NOT the full JASPAR database, which is not bundled in this deployment; an
  unrecognized `tf_name` fails loudly rather than fabricating a motif),
  `perform_pcr_and_gel_electrophoresis` (Tier A/C hybrid: real primer/region
  based amplicon simulation plus a *rendered, simulated* gel image -- clearly
  labeled as such, not a real wet-lab electrophoresis image),
  `analyze_protein_phylogeny` (real mafft/muscle/clustalw + fasttree/iqtree
  CLI wiring, argv-list subprocess calls only).
- Tier B (real numerical method, not a pretrained checkpoint):
  `bayesian_finemapping_with_deep_vi` (a genuine, simplified amortized
  variational-inference fine-mapping model: a small MLP encoder produces
  per-SNP spike-and-slab variational parameters, optimized against a real
  z-score/LD-based ELBO via gradient descent -- "simplified but genuine" per
  the catalog, not a lookup against any pretrained weights) and
  `fit_genomic_prediction_model` (real GBLUP: VanRaden genomic/dominance
  relationship matrix + REML heritability estimation + BLUP prediction).

Every file-path-shaped argument (`data_path`, `gwas_summary_path`,
`output_file`, `output_prefix`, `output_dir`) is passed through
`ensure_safe_relative_path` before being handed to the sandbox.
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


# ---------------------------------------------------------------------------
# liftover_coordinates
# ---------------------------------------------------------------------------


class LiftoverCoordinatesArgs(BaseModel):
    chromosome: str
    position: int
    input_format: str
    output_format: str
    data_path: str

    @field_validator("chromosome", "input_format", "output_format")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


def liftover_coordinates(arguments: dict, driver) -> dict:
    """hg19<->hg38 (or any other build pair the supplied chain file encodes)
    coordinate liftover via `pyliftover`. `data_path` must point at an
    already-obtained UCSC `.chain` file -- this deployment does not bundle
    chain files itself (see `backend/docs/tools/data_lake_source_list.md`)."""
    validated = LiftoverCoordinatesArgs.model_validate(arguments or {})
    data_path = ensure_safe_relative_path(validated.data_path)

    script_body = _dedent(
        """
        import json
        from pyliftover import LiftOver

        lo = LiftOver(_args["data_path"])
        converted = lo.convert_coordinate(_args["chromosome"], _args["position"])
        if not converted:
            result = {
                "chromosome": _args["chromosome"],
                "position": _args["position"],
                "input_format": _args["input_format"],
                "output_format": _args["output_format"],
                "lifted": False,
            }
        else:
            lifted_chrom, lifted_pos, strand, score = converted[0]
            result = {
                "chromosome": lifted_chrom,
                "position": lifted_pos,
                "strand": strand,
                "score": score,
                "input_format": _args["input_format"],
                "output_format": _args["output_format"],
                "lifted": True,
            }
        print(json.dumps(result))
        """
    )
    args = {
        "chromosome": validated.chromosome,
        "position": validated.position,
        "input_format": validated.input_format,
        "output_format": validated.output_format,
        "data_path": data_path,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# bayesian_finemapping_with_deep_vi
# ---------------------------------------------------------------------------


class BayesianFinemappingArgs(BaseModel):
    gwas_summary_path: str
    ld_matrix: List[List[float]]
    n_iterations: int = Field(default=5000, gt=0)
    learning_rate: float = Field(default=0.01, gt=0)
    hidden_dim: int = Field(default=64, gt=0)
    credible_threshold: float = Field(default=0.95, gt=0, le=1.0)

    @model_validator(mode="after")
    def _ld_matrix_is_square(self) -> "BayesianFinemappingArgs":
        n = len(self.ld_matrix)
        if n == 0:
            raise ValueError("ld_matrix must not be empty")
        if any(len(row) != n for row in self.ld_matrix):
            raise ValueError("ld_matrix must be a square (n_snps x n_snps) matrix")
        return self


def bayesian_finemapping_with_deep_vi(arguments: dict, driver) -> dict:
    """Bayesian fine-mapping via a real, simplified amortized deep
    variational-inference model: a small MLP encoder maps each SNP's z-score
    to spike-and-slab variational parameters (inclusion logit, effect mean,
    effect log-std), optimized by gradient descent against a genuine ELBO
    built from the z-score/LD-matrix fine-mapping likelihood
    (z ~ N(R @ beta, I)) plus KL terms against Bernoulli/Gaussian priors.
    Returns per-SNP posterior inclusion probabilities (PIPs) and a credible
    set at `credible_threshold`. This is a simplified but genuine VI fit, not
    a pretrained checkpoint."""
    validated = BayesianFinemappingArgs.model_validate(arguments or {})
    gwas_summary_path = ensure_safe_relative_path(validated.gwas_summary_path)

    script_body = _dedent(
        """
        import json
        import numpy as np
        import pandas as pd
        import torch
        import torch.nn as nn

        gwas_df = pd.read_csv(_args["gwas_summary_path"])
        if "z" in gwas_df.columns:
            z = gwas_df["z"].to_numpy(dtype=float)
        elif {"beta", "se"}.issubset(gwas_df.columns):
            z = (gwas_df["beta"] / gwas_df["se"]).to_numpy(dtype=float)
        else:
            raise ValueError(
                "gwas_summary_path must have a 'z' column, or both 'beta' and 'se' columns"
            )

        R = np.asarray(_args["ld_matrix"], dtype=float)
        n = z.shape[0]
        if R.shape != (n, n):
            raise ValueError(
                f"ld_matrix shape {R.shape} does not match the {n} SNPs in gwas_summary_path"
            )

        torch.manual_seed(0)
        z_t = torch.tensor(z, dtype=torch.float32)
        R_t = torch.tensor(R, dtype=torch.float32)
        z_in = z_t.unsqueeze(-1)

        hidden_dim = int(_args["hidden_dim"])
        encoder = nn.Sequential(
            nn.Linear(1, hidden_dim), nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim), nn.Tanh(),
            nn.Linear(hidden_dim, 3),  # logit_pi, mu, log_sigma per SNP
        )
        optimizer = torch.optim.Adam(encoder.parameters(), lr=float(_args["learning_rate"]))

        n_iterations = int(_args["n_iterations"])
        prior_pi = 1.0 / n
        temperature = 0.5
        for _ in range(n_iterations):
            optimizer.zero_grad()
            out = encoder(z_in)
            logit_pi, mu, log_sigma = out[:, 0], out[:, 1], out[:, 2]
            sigma = torch.nn.functional.softplus(log_sigma) + 1e-6
            pi = torch.sigmoid(logit_pi)

            beta_sample = mu + sigma * torch.randn_like(mu)
            u = torch.rand_like(pi).clamp(1e-6, 1 - 1e-6)
            gamma_logits = (
                torch.log(pi + 1e-9) - torch.log(1 - pi + 1e-9)
                + torch.log(u) - torch.log(1 - u)
            ) / temperature
            gamma_sample = torch.sigmoid(gamma_logits)
            effective_beta = gamma_sample * beta_sample

            z_pred = R_t @ effective_beta
            log_likelihood = -0.5 * torch.sum((z_t - z_pred) ** 2)

            kl_bernoulli = torch.sum(
                pi * torch.log((pi + 1e-9) / prior_pi)
                + (1 - pi) * torch.log((1 - pi + 1e-9) / (1 - prior_pi))
            )
            kl_gaussian = torch.sum(
                0.5 * (mu ** 2 + sigma ** 2 - 1 - torch.log(sigma ** 2 + 1e-9))
            )
            loss = -(log_likelihood - kl_bernoulli - kl_gaussian)
            loss.backward()
            optimizer.step()

        with torch.no_grad():
            out = encoder(z_in)
            pip = torch.sigmoid(out[:, 0]).numpy()

        order = np.argsort(-pip)
        cum = np.cumsum(pip[order])
        threshold = float(_args["credible_threshold"])
        total = cum[-1] if cum[-1] > 0 else 1.0
        cs_size = int(np.searchsorted(cum, threshold * total) + 1)
        cs_size = min(cs_size, n)
        credible_set = order[:cs_size].tolist()

        result = {
            "posterior_inclusion_probabilities": pip.tolist(),
            "credible_set_indices": credible_set,
            "credible_set_size": len(credible_set),
            "n_snps": n,
            "n_iterations": n_iterations,
            "credible_threshold": threshold,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "gwas_summary_path": gwas_summary_path,
        "ld_matrix": validated.ld_matrix,
        "n_iterations": validated.n_iterations,
        "learning_rate": validated.learning_rate,
        "hidden_dim": validated.hidden_dim,
        "credible_threshold": validated.credible_threshold,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_cas9_mutation_outcomes
# ---------------------------------------------------------------------------


class Cas9MutationOutcomesArgs(BaseModel):
    reference_sequences: Dict[str, str]
    edited_sequences: Dict[str, str]
    cell_line_info: Optional[Dict[str, Any]] = None
    output_prefix: str = "cas9_mutation_analysis"

    @field_validator("reference_sequences", "edited_sequences")
    @classmethod
    def _non_empty_dict(cls, value: Dict[str, str]) -> Dict[str, str]:
        if not value:
            raise ValueError("must be a non-empty mapping of sequence id -> sequence")
        return value


def analyze_cas9_mutation_outcomes(arguments: dict, driver) -> dict:
    """Categorizes Cas9-induced mutations by pairwise-aligning each matched
    reference/edited sequence pair (Biopython `Bio.Align.PairwiseAligner`,
    global alignment) and classifying the outcome as insertion / deletion /
    substitution / complex / no_edit, including frameshift status for
    indels."""
    validated = Cas9MutationOutcomesArgs.model_validate(arguments or {})
    output_prefix = ensure_safe_relative_path(validated.output_prefix)

    script_body = _dedent(
        """
        import json
        from Bio import Align

        reference_sequences = _args["reference_sequences"]
        edited_sequences = _args["edited_sequences"]
        output_prefix = _args["output_prefix"]

        aligner = Align.PairwiseAligner()
        aligner.mode = "global"
        aligner.open_gap_score = -10
        aligner.extend_gap_score = -0.5
        aligner.match_score = 2
        aligner.mismatch_score = -1

        per_sequence = {}
        mutation_type_counts = {
            "insertion": 0, "deletion": 0, "substitution": 0,
            "complex": 0, "no_edit": 0,
        }

        shared_ids = [sid for sid in reference_sequences if sid in edited_sequences]
        for seq_id in shared_ids:
            ref = str(reference_sequences[seq_id]).upper()
            edited = str(edited_sequences[seq_id]).upper()

            if ref == edited:
                per_sequence[seq_id] = {
                    "mutation_type": "no_edit", "indel_size": 0, "frameshift": False,
                }
                mutation_type_counts["no_edit"] += 1
                continue

            alignment = aligner.align(ref, edited)[0]
            aligned_ref = str(alignment[0])
            aligned_edited = str(alignment[1])
            ref_gaps = aligned_ref.count("-")
            edited_gaps = aligned_edited.count("-")
            mismatches = sum(
                1 for a, b in zip(aligned_ref, aligned_edited)
                if a != b and a != "-" and b != "-"
            )

            if ref_gaps > 0 and edited_gaps > 0:
                mutation_type = "complex"
            elif edited_gaps > 0:
                mutation_type = "deletion"
            elif ref_gaps > 0:
                mutation_type = "insertion"
            elif mismatches > 0:
                mutation_type = "substitution"
            else:
                mutation_type = "no_edit"

            length_delta = len(edited) - len(ref)
            indel_size = abs(length_delta)
            frameshift = bool(indel_size % 3 != 0) if indel_size > 0 else False

            per_sequence[seq_id] = {
                "mutation_type": mutation_type,
                "indel_size": indel_size,
                "length_delta": length_delta,
                "mismatches": mismatches,
                "frameshift": frameshift,
                "alignment_score": float(alignment.score),
            }
            mutation_type_counts[mutation_type] = mutation_type_counts.get(mutation_type, 0) + 1

        result = {
            "output_prefix": output_prefix,
            "per_sequence": per_sequence,
            "mutation_type_counts": mutation_type_counts,
            "cell_line_info": _args.get("cell_line_info"),
            "unmatched_reference_ids": [sid for sid in reference_sequences if sid not in edited_sequences],
        }
        with open(f"{output_prefix}_report.json", "w", encoding="utf-8") as fh:
            json.dump(result, fh)
        print(json.dumps(result))
        """
    )
    args = {
        "reference_sequences": validated.reference_sequences,
        "edited_sequences": validated.edited_sequences,
        "cell_line_info": validated.cell_line_info,
        "output_prefix": output_prefix,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_crispr_genome_editing
# ---------------------------------------------------------------------------


class CrisprGenomeEditingArgs(BaseModel):
    original_sequence: str
    edited_sequence: str
    guide_rna: str
    repair_template: Optional[str] = None

    @field_validator("original_sequence", "edited_sequence", "guide_rna")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


def analyze_crispr_genome_editing(arguments: dict, driver) -> dict:
    """Compares a pre-/post-CRISPR sequence pair: locates the guide RNA (and
    its NGG PAM, if present) in `original_sequence`, predicts the Cas9 cut
    site (3 bp upstream of the PAM), pairwise-aligns original vs edited
    (Biopython), and classifies the outcome as `hdr_precise` (when
    `repair_template` is supplied and found in the edited sequence),
    `nhej_indel`, `substitution`, or `no_edit`."""
    validated = CrisprGenomeEditingArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json
        from Bio import Align

        original = _args["original_sequence"].upper()
        edited = _args["edited_sequence"].upper()
        guide = _args["guide_rna"].upper()
        repair_template = _args.get("repair_template")

        guide_index = original.find(guide)
        pam_present = False
        cut_site = None
        if guide_index != -1:
            pam_start = guide_index + len(guide)
            pam = original[pam_start:pam_start + 3]
            pam_present = len(pam) == 3 and pam[1:] == "GG"
            cut_site = guide_index + len(guide) - 3

        aligner = Align.PairwiseAligner()
        aligner.mode = "global"
        aligner.open_gap_score = -10
        aligner.extend_gap_score = -0.5
        aligner.match_score = 2
        aligner.mismatch_score = -1
        alignment = aligner.align(original, edited)[0]
        aligned_original = str(alignment[0])
        aligned_edited = str(alignment[1])
        insertions = aligned_original.count("-")
        deletions = aligned_edited.count("-")

        if original == edited:
            edit_outcome = "no_edit"
        elif repair_template and repair_template.upper() in edited:
            edit_outcome = "hdr_precise"
        elif insertions > 0 or deletions > 0:
            edit_outcome = "nhej_indel"
        else:
            edit_outcome = "substitution"

        result = {
            "guide_found_in_original": guide_index != -1,
            "guide_index": guide_index if guide_index != -1 else None,
            "pam_present": pam_present,
            "predicted_cut_site": cut_site,
            "edit_outcome": edit_outcome,
            "length_delta": len(edited) - len(original),
            "insertions_in_alignment": insertions,
            "deletions_in_alignment": deletions,
            "alignment_score": float(alignment.score),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "original_sequence": validated.original_sequence,
        "edited_sequence": validated.edited_sequence,
        "guide_rna": validated.guide_rna,
        "repair_template": validated.repair_template,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# perform_crispr_cas9_genome_editing
# ---------------------------------------------------------------------------


class PerformCrisprCas9EditingArgs(BaseModel):
    guide_rna_sequences: List[str] = Field(min_length=1)
    target_genomic_loci: str
    cell_tissue_type: str

    @field_validator("guide_rna_sequences")
    @classmethod
    def _non_empty_guides(cls, value: List[str]) -> List[str]:
        cleaned = [g.strip() for g in value]
        if any(not g for g in cleaned):
            raise ValueError("guide_rna_sequences must not contain empty strings")
        return cleaned

    @field_validator("target_genomic_loci", "cell_tissue_type")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


def perform_crispr_cas9_genome_editing(arguments: dict, driver) -> dict:
    """Computational guide-design QC *simulation* of a CRISPR-Cas9 editing
    process: for each supplied guide RNA, searches `target_genomic_loci` for
    perfect and near-perfect (<=1 mismatch) matches with an NGG PAM, and
    reports on-target/off-target candidate counts plus basic guide QC
    metrics (GC content, length). This is NOT a wet-lab editing result --
    the sandboxed script's own output carries an explicit disclaimer."""
    validated = PerformCrisprCas9EditingArgs.model_validate(arguments or {})

    script_body = _dedent(
        """
        import json

        guides = _args["guide_rna_sequences"]
        locus = _args["target_genomic_loci"].upper()
        cell_tissue_type = _args["cell_tissue_type"]

        def gc_content(seq):
            seq = seq.upper()
            return (seq.count("G") + seq.count("C")) / len(seq) if seq else 0.0

        def find_matches(guide, sequence, max_mismatches=1):
            guide = guide.upper()
            n, m = len(sequence), len(guide)
            matches = []
            for i in range(max(n - m + 1, 0)):
                window = sequence[i:i + m]
                mismatches = sum(1 for a, b in zip(window, guide) if a != b)
                if mismatches <= max_mismatches:
                    pam = sequence[i + m:i + m + 3]
                    has_pam = len(pam) == 3 and pam[1:] == "GG"
                    matches.append({
                        "position": i, "mismatches": mismatches,
                        "pam": pam, "has_ngg_pam": has_pam,
                    })
            return matches

        guide_reports = []
        for guide in guides:
            matches = find_matches(guide, locus, max_mismatches=1)
            on_target = [m for m in matches if m["mismatches"] == 0 and m["has_ngg_pam"]]
            off_target = [m for m in matches if m["mismatches"] > 0 or not m["has_ngg_pam"]]
            guide_reports.append({
                "guide_rna": guide,
                "gc_content": gc_content(guide),
                "length": len(guide),
                "perfect_matches_with_pam": len(on_target),
                "predicted_off_target_sites_in_locus": len(off_target),
                "matches": matches,
            })

        result = {
            "simulation_disclaimer": (
                "Computational guide-design QC simulation only (on-target/off-target "
                "motif search within the supplied locus sequence) -- NOT a wet-lab "
                "editing result."
            ),
            "target_genomic_loci_length": len(locus),
            "cell_tissue_type": cell_tissue_type,
            "guides": guide_reports,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "guide_rna_sequences": validated.guide_rna_sequences,
        "target_genomic_loci": validated.target_genomic_loci,
        "cell_tissue_type": validated.cell_tissue_type,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# simulate_demographic_history
# ---------------------------------------------------------------------------

_SUPPORTED_DEMOGRAPHIC_MODELS = {"constant", "exponential_growth", "bottleneck"}
_SUPPORTED_COALESCENT_MODELS = {"kingman", "beta"}


class SimulateDemographicHistoryArgs(BaseModel):
    num_samples: int = Field(default=10, gt=0)
    sequence_length: int = Field(default=100_000, gt=0)
    recombination_rate: float = Field(default=1e-8, ge=0)
    mutation_rate: float = Field(default=1e-8, ge=0)
    demographic_model: str = "constant"
    demographic_params: Optional[Dict[str, Any]] = None
    coalescent_model: str = "kingman"
    beta_coalescent_param: Optional[float] = None
    random_seed: Optional[int] = None
    output_file: str = "simulated_sequences.vcf"

    @field_validator("demographic_model")
    @classmethod
    def _valid_demographic_model(cls, value: str) -> str:
        if value not in _SUPPORTED_DEMOGRAPHIC_MODELS:
            raise ValueError(f"demographic_model must be one of {sorted(_SUPPORTED_DEMOGRAPHIC_MODELS)}")
        return value

    @field_validator("coalescent_model")
    @classmethod
    def _valid_coalescent_model(cls, value: str) -> str:
        if value not in _SUPPORTED_COALESCENT_MODELS:
            raise ValueError(f"coalescent_model must be one of {sorted(_SUPPORTED_COALESCENT_MODELS)}")
        return value

    @model_validator(mode="after")
    def _beta_param_required_for_beta_coalescent(self) -> "SimulateDemographicHistoryArgs":
        if self.coalescent_model == "beta" and self.beta_coalescent_param is None:
            raise ValueError("beta_coalescent_param is required when coalescent_model='beta'")
        return self


def simulate_demographic_history(arguments: dict, driver) -> dict:
    """Real coalescent simulation via `msprime.sim_ancestry` +
    `msprime.sim_mutations`, writing a VCF of the simulated samples.
    Supports a constant-size, exponential-growth, or single-bottleneck
    single-population demography, under either the standard Kingman
    coalescent or a Beta-coalescent (multiple-merger) model."""
    validated = SimulateDemographicHistoryArgs.model_validate(arguments or {})
    output_file = ensure_safe_relative_path(validated.output_file)

    script_body = _dedent(
        """
        import json
        import msprime

        num_samples = int(_args["num_samples"])
        sequence_length = int(_args["sequence_length"])
        recombination_rate = float(_args["recombination_rate"])
        mutation_rate = float(_args["mutation_rate"])
        demographic_model = _args["demographic_model"]
        demographic_params = _args.get("demographic_params") or {}
        coalescent_model = _args["coalescent_model"]
        beta_coalescent_param = _args.get("beta_coalescent_param")
        random_seed = _args.get("random_seed")
        output_file = _args["output_file"]

        initial_size = float(
            demographic_params.get("population_size", demographic_params.get("initial_size", 10000))
        )
        demography = msprime.Demography()
        demography.add_population(name="pop0", initial_size=initial_size)

        if demographic_model == "exponential_growth":
            demography.populations[0].growth_rate = float(demographic_params.get("growth_rate", 0.0))
        elif demographic_model == "bottleneck":
            bottleneck_size = float(demographic_params.get("bottleneck_size", initial_size / 10))
            bottleneck_time = float(demographic_params.get("bottleneck_time", 100))
            recovery_size = float(demographic_params.get("recovery_size", initial_size))
            demography.add_population_parameters_change(
                time=bottleneck_time, population="pop0", initial_size=bottleneck_size,
            )
            demography.add_population_parameters_change(
                time=bottleneck_time * 2, population="pop0", initial_size=recovery_size,
            )

        if coalescent_model == "kingman":
            ancestry_model = "hudson"
        else:
            ancestry_model = msprime.BetaCoalescent(alpha=float(beta_coalescent_param))

        ts = msprime.sim_ancestry(
            samples={"pop0": num_samples},
            sequence_length=sequence_length,
            recombination_rate=recombination_rate,
            demography=demography,
            model=ancestry_model,
            random_seed=random_seed,
        )
        ts = msprime.sim_mutations(ts, rate=mutation_rate, random_seed=random_seed)

        with open(output_file, "w") as fh:
            ts.write_vcf(fh)

        result = {
            "output_file": output_file,
            "num_samples": num_samples,
            "sequence_length": sequence_length,
            "num_trees": ts.num_trees,
            "num_sites": ts.num_sites,
            "num_mutations": ts.num_mutations,
            "demographic_model": demographic_model,
            "coalescent_model": coalescent_model,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "num_samples": validated.num_samples,
        "sequence_length": validated.sequence_length,
        "recombination_rate": validated.recombination_rate,
        "mutation_rate": validated.mutation_rate,
        "demographic_model": validated.demographic_model,
        "demographic_params": validated.demographic_params,
        "coalescent_model": validated.coalescent_model,
        "beta_coalescent_param": validated.beta_coalescent_param,
        "random_seed": validated.random_seed,
        "output_file": output_file,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# identify_transcription_factor_binding_sites
# ---------------------------------------------------------------------------

# Small built-in reference set of well-established, published consensus
# transcription-factor binding motifs (textbook/IUPAC-degenerate-code level).
# This is deliberately NOT a stand-in for the full JASPAR database, which is
# not bundled in this deployment (no data-lake/network access from inside
# the sandbox by default) -- an unrecognized `tf_name` fails loudly in the
# sandboxed script rather than fabricating a motif.
_KNOWN_TF_CONSENSUS = {
    "TP53": "RRRCWWGYYY",
    "SP1": "GGGGCGGGGC",
    "AP1": "TGASTCA",
    "CREB": "TGACGTCA",
    "MYC": "CACGTG",
    "GATA1": "WGATAR",
    "NFKB": "GGGRNWYYCC",
    "OCT4": "ATGCAAAT",
    "TATA": "TATAWAAR",
    "CEBPA": "ATTGCGCAAT",
}

_IUPAC_CODES = {
    "A": "A", "C": "C", "G": "G", "T": "T",
    "R": "AG", "Y": "CT", "S": "GC", "W": "AT",
    "K": "GT", "M": "AC", "B": "CGT", "D": "AGT",
    "H": "ACT", "V": "ACG", "N": "ACGT",
}


class IdentifyTFBindingSitesArgs(BaseModel):
    sequence: str
    tf_name: str
    threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    output_file: Optional[str] = None

    @field_validator("sequence", "tf_name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


def identify_transcription_factor_binding_sites(arguments: dict, driver) -> dict:
    """Scans `sequence` (both strands) for matches to `tf_name`'s consensus
    binding motif using a real position-weight-matrix (PWM) sliding-window
    log-odds scan against uniform (0.25) background, reporting matches whose
    relative score (normalized between the PWM's theoretical min/max) is
    >= `threshold`. Motifs come from a small bundled reference set of
    published consensus sequences (see `_KNOWN_TF_CONSENSUS`) -- an
    unsupported `tf_name` raises a clear error rather than a fabricated
    motif."""
    validated = IdentifyTFBindingSitesArgs.model_validate(arguments or {})
    output_file = ensure_safe_relative_path(validated.output_file) if validated.output_file else None

    script_body = _dedent(
        """
        import json
        import math
        from Bio.Seq import Seq

        known_tf_consensus = _args["known_tf_consensus"]
        iupac_codes = _args["iupac_codes"]
        tf_name = _args["tf_name"].upper()
        if tf_name not in known_tf_consensus:
            raise ValueError(
                f"Unsupported tf_name {_args['tf_name']!r}. This deployment bundles a "
                f"small reference set of consensus motifs ({', '.join(sorted(known_tf_consensus))}); "
                "the full JASPAR database is not bundled locally."
            )

        def build_pwm(consensus, pseudocount=0.5, total=100.0):
            pwm = []
            for ch in consensus.upper():
                allowed = iupac_codes.get(ch, "ACGT")
                remaining = 4 - len(allowed)
                base_share = (total - pseudocount * remaining) / len(allowed)
                pwm.append({
                    b: (base_share if b in allowed else pseudocount) / total
                    for b in "ACGT"
                })
            return pwm

        def score_window(window, pwm, background=0.25):
            score = 0.0
            for base, freqs in zip(window, pwm):
                score += math.log2(freqs.get(base, 1e-4) / background)
            return score

        def scan(sequence, pwm):
            motif_len = len(pwm)
            max_score = sum(math.log2(max(freqs.values()) / 0.25) for freqs in pwm)
            min_score = sum(math.log2(min(freqs.values()) / 0.25) for freqs in pwm)
            denom = (max_score - min_score) or 1.0
            hits = []
            for i in range(max(len(sequence) - motif_len + 1, 0)):
                window = sequence[i:i + motif_len]
                raw = score_window(window, pwm)
                hits.append((i, raw, (raw - min_score) / denom))
            return hits

        sequence = _args["sequence"].upper()
        threshold = float(_args["threshold"])
        pwm = build_pwm(known_tf_consensus[tf_name])
        motif_len = len(pwm)

        rev_seq = str(Seq(sequence).reverse_complement())
        matches = []
        for i, raw, relative in scan(sequence, pwm):
            if relative >= threshold:
                matches.append({
                    "strand": "+", "position": i, "raw_score": raw, "relative_score": relative,
                    "matched_sequence": sequence[i:i + motif_len],
                })
        for i, raw, relative in scan(rev_seq, pwm):
            if relative >= threshold:
                matches.append({
                    "strand": "-", "position": len(sequence) - motif_len - i,
                    "raw_score": raw, "relative_score": relative,
                    "matched_sequence": rev_seq[i:i + motif_len],
                })
        matches.sort(key=lambda m: m["position"])

        result = {
            "tf_name": tf_name,
            "consensus_motif": known_tf_consensus[tf_name],
            "threshold": threshold,
            "matches": matches,
            "num_matches": len(matches),
        }
        output_file = _args.get("output_file")
        if output_file:
            with open(output_file, "w", encoding="utf-8") as fh:
                json.dump(result, fh)
        print(json.dumps(result))
        """
    )
    args = {
        "sequence": validated.sequence,
        "tf_name": validated.tf_name,
        "threshold": validated.threshold,
        "output_file": output_file,
        "known_tf_consensus": _KNOWN_TF_CONSENSUS,
        "iupac_codes": _IUPAC_CODES,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# fit_genomic_prediction_model
# ---------------------------------------------------------------------------


class FitGenomicPredictionModelArgs(BaseModel):
    genotypes: List[List[float]]
    phenotypes: List[float]
    fixed_effects: Optional[List[List[float]]] = None
    model_type: str = "additive"
    output_file: str = "genomic_prediction_results.csv"

    @field_validator("model_type")
    @classmethod
    def _valid_model_type(cls, value: str) -> str:
        if value not in {"additive", "dominance"}:
            raise ValueError("model_type must be one of ['additive', 'dominance']")
        return value

    @model_validator(mode="after")
    def _shapes_are_consistent(self) -> "FitGenomicPredictionModelArgs":
        if not self.genotypes:
            raise ValueError("genotypes must not be empty")
        n_markers = len(self.genotypes[0])
        if any(len(row) != n_markers for row in self.genotypes):
            raise ValueError("genotypes must be a rectangular n_samples x n_markers matrix")
        n_samples = len(self.genotypes)
        if len(self.phenotypes) != n_samples:
            raise ValueError(
                f"phenotypes length ({len(self.phenotypes)}) must match genotypes rows ({n_samples})"
            )
        if self.fixed_effects is not None and len(self.fixed_effects) != n_samples:
            raise ValueError(
                f"fixed_effects rows ({len(self.fixed_effects)}) must match genotypes rows ({n_samples})"
            )
        return self


def fit_genomic_prediction_model(arguments: dict, driver) -> dict:
    """Real genomic-prediction (GBLUP) model: builds a VanRaden additive (or
    dominance) genomic relationship matrix from `genotypes`, estimates
    narrow-sense heritability via a profiled REML likelihood over the
    mixed model y = X*beta + u + e (u ~ N(0, G*sigma_a^2)), and returns
    BLUP genomic estimated breeding values (GEBVs), writing a CSV report to
    `output_file`."""
    validated = FitGenomicPredictionModelArgs.model_validate(arguments or {})
    output_file = ensure_safe_relative_path(validated.output_file)

    script_body = _dedent(
        """
        import json
        import numpy as np
        from scipy.optimize import minimize_scalar

        genotypes = np.asarray(_args["genotypes"], dtype=float)
        phenotypes = np.asarray(_args["phenotypes"], dtype=float)
        model_type = _args["model_type"]
        output_file = _args["output_file"]
        n = genotypes.shape[0]

        fixed_effects = _args.get("fixed_effects")
        if fixed_effects:
            X = np.column_stack([np.ones(n), np.asarray(fixed_effects, dtype=float)])
        else:
            X = np.ones((n, 1))

        def compute_relationship_matrix(geno, model):
            p = geno.mean(axis=0) / 2.0
            if model == "additive":
                Z = geno - 2 * p
                denom = 2 * np.sum(p * (1 - p))
                denom = denom if denom > 1e-8 else 1.0
                return (Z @ Z.T) / denom
            q = 1 - p
            het_indicator = (geno == 1).astype(float)
            W = het_indicator - 2 * p * q
            denom = np.sum((2 * p * q) ** 2)
            denom = denom if denom > 1e-8 else 1.0
            return (W @ W.T) / denom

        G = compute_relationship_matrix(genotypes, model_type)
        G = G + np.eye(n) * 1e-6

        def neg2_reml(h2, G, X, y):
            V = h2 * G + (1 - h2) * np.eye(n)
            V_inv = np.linalg.pinv(V)
            XtVinvX = X.T @ V_inv @ X
            XtVinvX_inv = np.linalg.pinv(XtVinvX)
            beta = XtVinvX_inv @ X.T @ V_inv @ y
            resid = y - X @ beta
            _, logdet_V = np.linalg.slogdet(V)
            _, logdet_XtVinvX = np.linalg.slogdet(XtVinvX)
            rss = float(resid.T @ V_inv @ resid)
            p_ = X.shape[1]
            sigma2_hat = max(rss / max(n - p_, 1), 1e-8)
            return logdet_V + logdet_XtVinvX + (n - p_) * np.log(sigma2_hat)

        res = minimize_scalar(
            neg2_reml, bounds=(1e-4, 1 - 1e-4), method="bounded", args=(G, X, phenotypes),
        )
        h2_hat = float(res.x)

        Vstar = h2_hat * G + (1 - h2_hat) * np.eye(n)
        Vstar_inv = np.linalg.pinv(Vstar)
        XtVinvX_inv = np.linalg.pinv(X.T @ Vstar_inv @ X)
        beta_hat = XtVinvX_inv @ X.T @ Vstar_inv @ phenotypes
        resid = phenotypes - X @ beta_hat
        u_hat = h2_hat * G @ Vstar_inv @ resid
        gebv = X @ beta_hat + u_hat

        with open(output_file, "w") as fh:
            fh.write("sample_index,gebv,breeding_value\\n")
            for i in range(n):
                fh.write(f"{i},{gebv[i]:.6f},{u_hat[i]:.6f}\\n")

        result = {
            "output_file": output_file,
            "model_type": model_type,
            "heritability_estimate": h2_hat,
            "n_samples": n,
            "n_markers": int(genotypes.shape[1]),
            "gebv": gebv.tolist(),
            "breeding_values": u_hat.tolist(),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "genotypes": validated.genotypes,
        "phenotypes": validated.phenotypes,
        "fixed_effects": validated.fixed_effects,
        "model_type": validated.model_type,
        "output_file": output_file,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# perform_pcr_and_gel_electrophoresis
# ---------------------------------------------------------------------------


class PerformPcrAndGelElectrophoresisArgs(BaseModel):
    genomic_dna: str
    forward_primer: Optional[str] = None
    reverse_primer: Optional[str] = None
    target_region: Optional[Tuple[int, int]] = None
    annealing_temp: float = 58
    extension_time: int = 30
    cycles: int = 35
    gel_percentage: float = 2.0
    output_prefix: str = "pcr_result"

    @field_validator("genomic_dna")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("genomic_dna must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _has_amplification_strategy(self) -> "PerformPcrAndGelElectrophoresisArgs":
        has_primers = bool(self.forward_primer and self.reverse_primer)
        if not has_primers and self.target_region is None:
            raise ValueError(
                "provide either both forward_primer and reverse_primer, or target_region"
            )
        return self


def perform_pcr_and_gel_electrophoresis(arguments: dict, driver) -> dict:
    """Simulates PCR amplification (primer-pair binding-site search, or a
    directly supplied `target_region`) and renders a *simulated* agarose gel
    image (matplotlib) showing the predicted amplicon migrating against a
    standard DNA ladder. Tier A/C hybrid: real amplicon-length computation,
    but the gel image is a rendered simulation, not a real wet-lab
    electrophoresis photograph -- documented as such in the result."""
    validated = PerformPcrAndGelElectrophoresisArgs.model_validate(arguments or {})
    output_prefix = ensure_safe_relative_path(validated.output_prefix)

    script_body = _dedent(
        """
        import json
        import math
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        genomic_dna = _args["genomic_dna"].upper()
        forward_primer = _args.get("forward_primer")
        reverse_primer = _args.get("reverse_primer")
        target_region = _args.get("target_region")
        annealing_temp = _args["annealing_temp"]
        extension_time = _args["extension_time"]
        cycles = _args["cycles"]
        gel_percentage = _args["gel_percentage"]
        output_prefix = _args["output_prefix"]

        def revcomp(seq):
            return seq.translate(str.maketrans("ACGT", "TGCA"))[::-1]

        if forward_primer and reverse_primer:
            fwd = forward_primer.upper()
            rev_rc = revcomp(reverse_primer.upper())
            fwd_pos = genomic_dna.find(fwd)
            rev_pos = genomic_dna.find(rev_rc)
            if fwd_pos == -1 or rev_pos == -1:
                raise ValueError("forward and/or reverse primer binding site not found in genomic_dna")
            if rev_pos + len(rev_rc) <= fwd_pos:
                raise ValueError("reverse primer site is not downstream of forward primer site")
            start, end = fwd_pos, rev_pos + len(rev_rc)
        else:
            start, end = int(target_region[0]), int(target_region[1])
        amplicon = genomic_dna[start:end]
        amplicon_length = len(amplicon)

        ladder_sizes = [10000, 8000, 6000, 5000, 4000, 3000, 2000, 1500, 1000, 750, 500, 250, 100]
        gel_len = 400.0
        log_min, log_max = math.log10(min(ladder_sizes)), math.log10(max(ladder_sizes))

        def migration(size):
            log_size = math.log10(max(size, 1))
            fraction = (log_max - log_size) / (log_max - log_min)
            return max(min(fraction, 1.0), 0.0) * gel_len

        fig, ax = plt.subplots(figsize=(3, 5))
        ax.set_xlim(0, 2)
        ax.set_ylim(0, gel_len)
        ax.invert_yaxis()
        ax.set_xticks([0.5, 1.5])
        ax.set_xticklabels(["Ladder", "Sample"])
        ax.set_ylabel("Simulated migration distance")
        for size in ladder_sizes:
            y = migration(size)
            ax.hlines(y, 0.2, 0.8, color="gray", linewidth=2)
            ax.text(0.05, y, str(size), fontsize=6, va="center", ha="right")
        sample_y = migration(amplicon_length)
        ax.hlines(sample_y, 1.2, 1.8, color="black", linewidth=3)
        ax.text(1.9, sample_y, f"{amplicon_length} bp", fontsize=7, va="center")
        ax.set_title(f"{gel_percentage}% agarose gel (simulated)")
        gel_path = f"{output_prefix}_gel.png"
        fig.tight_layout()
        fig.savefig(gel_path, dpi=150)
        plt.close(fig)

        result = {
            "amplicon_length": amplicon_length,
            "amplicon_sequence": amplicon,
            "start": start,
            "end": end,
            "annealing_temp": annealing_temp,
            "extension_time": extension_time,
            "cycles": cycles,
            "gel_percentage": gel_percentage,
            "gel_image_path": gel_path,
            "disclaimer": (
                "Simulated PCR amplicon + a rendered, simulated gel image -- "
                "not a real wet-lab electrophoresis result."
            ),
        }
        print(json.dumps(result))
        """
    )
    args = {
        "genomic_dna": validated.genomic_dna,
        "forward_primer": validated.forward_primer,
        "reverse_primer": validated.reverse_primer,
        "target_region": list(validated.target_region) if validated.target_region else None,
        "annealing_temp": validated.annealing_temp,
        "extension_time": validated.extension_time,
        "cycles": validated.cycles,
        "gel_percentage": validated.gel_percentage,
        "output_prefix": output_prefix,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# analyze_protein_phylogeny
# ---------------------------------------------------------------------------

_SUPPORTED_ALIGNMENT_METHODS = {"mafft", "muscle", "clustalw"}
_SUPPORTED_TREE_METHODS = {"fasttree", "iqtree"}


class AnalyzeProteinPhylogenyArgs(BaseModel):
    fasta_sequences: str
    output_dir: str = "./"
    alignment_method: str = "clustalw"
    tree_method: str = "fasttree"

    @field_validator("fasta_sequences")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("fasta_sequences must be non-empty FASTA text")
        return value

    @field_validator("alignment_method")
    @classmethod
    def _valid_alignment_method(cls, value: str) -> str:
        if value not in _SUPPORTED_ALIGNMENT_METHODS:
            raise ValueError(f"alignment_method must be one of {sorted(_SUPPORTED_ALIGNMENT_METHODS)}")
        return value

    @field_validator("tree_method")
    @classmethod
    def _valid_tree_method(cls, value: str) -> str:
        if value not in _SUPPORTED_TREE_METHODS:
            raise ValueError(f"tree_method must be one of {sorted(_SUPPORTED_TREE_METHODS)}")
        return value


def analyze_protein_phylogeny(arguments: dict, driver) -> dict:
    """Multiple sequence alignment (mafft/muscle/clustalw CLI) followed by
    phylogenetic tree inference (fasttree/iqtree CLI) over `fasta_sequences`
    (literal multi-FASTA text, not a file path). All external tools are
    invoked via argv-list `subprocess.run` calls inside the sandbox --
    `_args` values are only ever used as data (file contents/paths), never
    interpolated into a shell command string."""
    validated = AnalyzeProteinPhylogenyArgs.model_validate(arguments or {})
    output_dir = ensure_safe_relative_path(validated.output_dir)

    script_body = _dedent(
        """
        import json
        import os
        import subprocess

        fasta_sequences = _args["fasta_sequences"]
        output_dir = _args["output_dir"]
        alignment_method = _args["alignment_method"]
        tree_method = _args["tree_method"]

        os.makedirs(output_dir, exist_ok=True)
        input_fasta = os.path.join(output_dir, "input_sequences.fasta")
        with open(input_fasta, "w", encoding="utf-8") as fh:
            fh.write(fasta_sequences)

        aligned_fasta = os.path.join(output_dir, "aligned.fasta")

        if alignment_method == "mafft":
            with open(aligned_fasta, "w") as out_fh:
                proc = subprocess.run(
                    ["mafft", "--auto", input_fasta],
                    stdout=out_fh, stderr=subprocess.PIPE, text=True,
                )
            if proc.returncode != 0:
                raise RuntimeError(f"mafft failed: {proc.stderr}")
        elif alignment_method == "muscle":
            proc = subprocess.run(
                ["muscle", "-align", input_fasta, "-output", aligned_fasta],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"muscle failed: {proc.stderr}")
        else:
            proc = subprocess.run(
                ["clustalw", f"-INFILE={input_fasta}", "-OUTPUT=FASTA", f"-OUTFILE={aligned_fasta}"],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"clustalw failed: {proc.stderr}")

        tree_file = os.path.join(output_dir, "tree.nwk")
        if tree_method == "fasttree":
            with open(tree_file, "w") as out_fh:
                proc = subprocess.run(
                    ["fasttree", aligned_fasta], stdout=out_fh, stderr=subprocess.PIPE, text=True,
                )
            if proc.returncode != 0:
                raise RuntimeError(f"fasttree failed: {proc.stderr}")
        else:
            proc = subprocess.run(
                ["iqtree", "-s", aligned_fasta, "-nt", "1"], capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"iqtree failed: {proc.stderr}")
            tree_file = aligned_fasta + ".treefile"

        with open(tree_file, encoding="utf-8") as fh:
            newick_tree = fh.read().strip()

        result = {
            "output_dir": output_dir,
            "alignment_file": aligned_fasta,
            "tree_file": tree_file,
            "alignment_method": alignment_method,
            "tree_method": tree_method,
            "newick_tree": newick_tree,
        }
        print(json.dumps(result))
        """
    )
    args = {
        "fasta_sequences": validated.fasta_sequences,
        "output_dir": output_dir,
        "alignment_method": validated.alignment_method,
        "tree_method": validated.tree_method,
    }
    return run_in_sandbox(driver, script_body=script_body, args=args)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_TOOL_HANDLERS = {
    "liftover_coordinates": liftover_coordinates,
    "bayesian_finemapping_with_deep_vi": bayesian_finemapping_with_deep_vi,
    "analyze_cas9_mutation_outcomes": analyze_cas9_mutation_outcomes,
    "analyze_crispr_genome_editing": analyze_crispr_genome_editing,
    "perform_crispr_cas9_genome_editing": perform_crispr_cas9_genome_editing,
    "simulate_demographic_history": simulate_demographic_history,
    "identify_transcription_factor_binding_sites": identify_transcription_factor_binding_sites,
    "fit_genomic_prediction_model": fit_genomic_prediction_model,
    "perform_pcr_and_gel_electrophoresis": perform_pcr_and_gel_electrophoresis,
    "analyze_protein_phylogeny": analyze_protein_phylogeny,
}


def register_genomics_popgen_tools(registry, driver) -> List[str]:
    """Registers every Genomics & population genetics action tool into
    `registry`, each bound to the shared sandbox `driver`. Returns the list
    of registered tool names."""
    for name, handler in _TOOL_HANDLERS.items():
        registry.register_server(name, functools.partial(handler, driver=driver))
    return list(_TOOL_HANDLERS.keys())
