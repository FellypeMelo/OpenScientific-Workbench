"""Immunology action tools (Fase 5, "Categoria: Imunologia" of
`backend/docs/tools/action_tool_catalog.md`).

Every handler below follows the shared Fase 5 pattern (see
`_sandbox_tool_base.py`'s module docstring for the full rationale):

1. Validate the incoming ``arguments`` dict with a Pydantic model.
2. Path-guard any file-path argument via
   ``domain/services/path_guard.py::ensure_safe_relative_path``.
3. Build a short, hand-written ``script_body`` with the real scientific
   logic and run it inside the bwrap sandbox via ``run_in_sandbox`` -- never
   in-process. ``args`` are always passed as data (a JSON file read back
   inside the sandbox as ``_args``), never interpolated into the script
   source, so an externally-influenced value can never be mistaken for code.

Tiering (per the catalog's own A/B/C/D rubric -- only ``isolate_purify_immune_cells``
carries an explicit tier tag in the catalog text; the rest are derived here
using the same rubric the catalog defines and the precedent set by sibling
categories, e.g. flow-cytometry/imaging tools are tiered alongside the "Cell
biology & imaging" category's own Tier C heading even when the payload is
numeric FCS event data rather than a raster image):

- ``isolate_purify_immune_cells`` -- Tier A (deterministic protocol
  generator, catalog says so explicitly).
- ``track_immune_cells_under_flow`` -- Tier C (trackpy-based cell tracking,
  general-purpose image pipeline).
- ``analyze_cytokine_production_in_cd4_tcells`` -- Tier C (flow-cytometry
  gating via a heuristic percentile threshold against a negative control --
  same tier as the sibling flow-cytometry tools in the imaging category).
- ``analyze_ebv_antibody_titers`` -- Tier B (real scipy 4-parameter-logistic
  curve fit, closed-form inversion -- same family as
  ``analyze_atp_luminescence_assay``'s standard-curve fit).
- ``analyze_cns_lesion_histology`` -- Tier C (scikit-image color
  deconvolution + Otsu thresholding, general-purpose).
- ``analyze_immunohistochemistry_image`` -- Tier C (scikit-image DAB color
  deconvolution + Otsu thresholding, general-purpose).

No Tier D tool exists in this category -- every tool here is a real,
implementable pipeline, so nothing in this module touches
`backend/docs/tools/UNSUPPORTED.md`.
"""
import functools
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.domain.services.path_guard import ensure_safe_relative_path
from src.infrastructure.tools._sandbox_tool_base import run_in_sandbox

# ---------------------------------------------------------------------------
# Argument models
# ---------------------------------------------------------------------------


class IsolateImmuneCellsArgs(BaseModel):
    """Args for `isolate_purify_immune_cells` (Tier A protocol generator)."""

    tissue_type: str = Field(..., min_length=1)
    target_cell_type: str = Field(..., min_length=1)
    enzyme_type: str = Field("collagenase", min_length=1)
    macs_antibody: Optional[str] = None
    digestion_time_min: int = Field(45, gt=0, le=480)


class ImmuneCellFlowTrackingArgs(BaseModel):
    """Args for `track_immune_cells_under_flow` (Tier C trackpy pipeline)."""

    image_sequence_path: str = Field(..., min_length=1)
    output_dir: str = "./output"
    pixel_size_um: float = Field(1.0, gt=0)
    time_interval_sec: float = Field(1.0, gt=0)
    flow_direction: Literal["right", "left", "up", "down"] = "right"


class CytokineProductionArgs(BaseModel):
    """Args for `analyze_cytokine_production_in_cd4_tcells` (Tier C FCS gating)."""

    fcs_files_dict: Dict[str, str] = Field(..., min_length=1)
    output_dir: str = "./results"


class EbvAntibodyTitersArgs(BaseModel):
    """Args for `analyze_ebv_antibody_titers` (Tier B 4PL curve fit)."""

    raw_od_data: Dict[str, float] = Field(..., min_length=1)
    standard_curve_data: Dict[str, Any]
    sample_metadata: Dict[str, Any] = Field(default_factory=dict)
    output_dir: str = "./"

    @field_validator("standard_curve_data")
    @classmethod
    def _validate_standard_curve(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        concentrations = value.get("concentrations")
        od_values = value.get("od_values")
        if not isinstance(concentrations, list) or not isinstance(od_values, list):
            raise ValueError(
                "standard_curve_data must contain 'concentrations' and 'od_values' lists."
            )
        if len(concentrations) < 4 or len(concentrations) != len(od_values):
            raise ValueError(
                "standard_curve_data 'concentrations' and 'od_values' must be equal-length "
                "lists with at least 4 points (required for a 4-parameter logistic fit)."
            )
        return value


class CnsLesionHistologyArgs(BaseModel):
    """Args for `analyze_cns_lesion_histology` (Tier C image pipeline)."""

    image_path: str = Field(..., min_length=1)
    output_dir: str = "./output"
    stain_type: str = Field("H&E", min_length=1)


class IhcImageArgs(BaseModel):
    """Args for `analyze_immunohistochemistry_image` (Tier C image pipeline)."""

    image_path: str = Field(..., min_length=1)
    protein_name: str = "Unknown"
    output_dir: str = "./ihc_results/"


# ---------------------------------------------------------------------------
# script_body constants -- real, hand-written scientific logic. `_args` is
# injected by `run_in_sandbox`; none of these define it or read `sys.argv`.
# ---------------------------------------------------------------------------

_ISOLATE_PROTOCOL_SCRIPT = """
tissue_type = _args["tissue_type"]
target_cell_type = _args["target_cell_type"]
enzyme_type_raw = _args["enzyme_type"]
enzyme_type = enzyme_type_raw.strip().lower()
macs_antibody = _args.get("macs_antibody")
digestion_time_min = _args["digestion_time_min"]

# Standard enzymatic tissue-dissociation cocktails (recipe + temperature),
# drawn from established immunology single-cell-isolation protocols.
ENZYME_PROTOCOLS = {
    "collagenase": {
        "recipe": "1 mg/mL Collagenase IV + 100 U/mL DNase I in HBSS (with Ca2+/Mg2+)",
        "temperature_c": 37,
    },
    "dispase": {
        "recipe": "2 mg/mL Dispase II + 100 U/mL DNase I in HBSS",
        "temperature_c": 37,
    },
    "trypsin": {
        "recipe": "0.25% Trypsin-EDTA",
        "temperature_c": 37,
    },
    "papain": {
        "recipe": "20 U/mL Papain + 100 U/mL DNase I in HBSS, activated with 1 mM L-cysteine",
        "temperature_c": 37,
    },
    "liberase": {
        "recipe": "0.5 mg/mL Liberase TL + 100 U/mL DNase I in HBSS",
        "temperature_c": 37,
    },
}
enzyme_info = ENZYME_PROTOCOLS.get(
    enzyme_type,
    {
        "recipe": enzyme_type_raw + " per manufacturer instructions + 100 U/mL DNase I",
        "temperature_c": 37,
    },
)

# Common lineage-defining surface markers per target cell type, used to
# suggest a MACS marker when the caller didn't specify one.
CELL_TYPE_MARKERS = [
    ("cd4 t cell", "CD4"),
    ("cd8 t cell", "CD8"),
    ("treg", "CD25"),
    ("t cell", "CD3"),
    ("b cell", "CD19"),
    ("nk cell", "CD56"),
    ("macrophage", "CD11b"),
    ("monocyte", "CD14"),
    ("dendritic cell", "CD11c"),
    ("neutrophil", "Ly6G"),
]
target_lower = target_cell_type.lower()
suggested_marker = None
for key, marker in CELL_TYPE_MARKERS:
    if key in target_lower:
        suggested_marker = marker
        break
macs_marker = macs_antibody or suggested_marker

needs_rbc_lysis = any(tag in tissue_type.lower() for tag in ("blood", "spleen", "bone marrow"))

steps = [
    "1. Harvest " + tissue_type + " and place immediately into ice-cold HBSS or PBS.",
    "2. Mechanically mince the tissue into <2 mm fragments using sterile scalpels/scissors.",
    (
        "3. Enzymatic digestion: incubate minced tissue in " + enzyme_info["recipe"]
        + " at " + str(enzyme_info["temperature_c"]) + " C with gentle agitation for "
        + str(digestion_time_min) + " minutes."
    ),
    "4. Quench digestion with an equal volume of complete medium containing 10% FBS.",
    "5. Filter the digest through a 70 um cell strainer to obtain a single-cell suspension.",
    "6. Centrifuge at 300 x g for 5 minutes at 4 C and discard the supernatant.",
]
step_n = 7
if needs_rbc_lysis:
    steps.append(
        str(step_n) + ". Resuspend the pellet in 1-2 mL ACK lysis buffer for 3-5 minutes at "
        "room temperature to remove red blood cells, then wash with 10 mL complete medium."
    )
    step_n += 1

steps.append(
    str(step_n) + ". Resuspend cells in MACS buffer (PBS + 0.5% BSA + 2 mM EDTA) and count "
    "viable cells via trypan blue exclusion."
)
step_n += 1

if macs_marker:
    steps.append(
        str(step_n) + ". Label cells with anti-" + macs_marker + " MACS microbeads (target: "
        + target_cell_type + ") per manufacturer protocol (typically 10 uL beads per 1e7 "
        "cells, 15 minutes at 4 C in the dark)."
    )
    step_n += 1
    steps.append(
        str(step_n) + ". Positively select " + target_cell_type + " on an LS/MS MACS column "
        "per the kit's magnetic separator protocol; collect the labeled (bound) fraction as "
        "the purified population."
    )
    step_n += 1
else:
    steps.append(
        str(step_n) + ". No MACS antibody specified: proceed with FACS sorting for "
        + target_cell_type + " using an appropriate surface-marker antibody panel."
    )
    step_n += 1

steps.append(
    str(step_n) + ". Assess purity by flow cytometry (target: >90% purity for the isolated "
    + target_cell_type + " population) before downstream use."
)

result = {
    "tissue_type": tissue_type,
    "target_cell_type": target_cell_type,
    "enzyme_type": enzyme_type_raw,
    "digestion_buffer": enzyme_info["recipe"],
    "digestion_temperature_c": enzyme_info["temperature_c"],
    "digestion_time_min": digestion_time_min,
    "suggested_macs_marker": macs_marker,
    "rbc_lysis_included": needs_rbc_lysis,
    "protocol_steps": steps,
}
print(_json.dumps(result))
"""

_TRACK_IMMUNE_CELLS_FLOW_SCRIPT = """
import os

import numpy as np
import skimage.io as skio
import trackpy as tp

seq_path = "/workspace/" + _args["image_sequence_path"]
output_dir = "/workspace/" + _args["output_dir"]
pixel_size_um = _args["pixel_size_um"]
time_interval_sec = _args["time_interval_sec"]
flow_direction = _args["flow_direction"]

os.makedirs(output_dir, exist_ok=True)

frames = skio.imread_collection(os.path.join(seq_path, "*"))
if len(frames) == 0:
    raise FileNotFoundError("No images found in " + seq_path)

features = tp.batch(list(frames), diameter=15, minmass=100)
tracks = tp.link(features, search_range=15, memory=3)
tracks = tp.filter_stubs(tracks, threshold=3)

direction_vectors = {"right": (1, 0), "left": (-1, 0), "up": (0, -1), "down": (0, 1)}
direction_vec = direction_vectors[flow_direction]

cell_results = []
for particle_id, group in tracks.groupby("particle"):
    group = group.sort_values("frame")
    xs = group["x"].to_numpy() * pixel_size_um
    ys = group["y"].to_numpy() * pixel_size_um
    dx = np.diff(xs)
    dy = np.diff(ys)
    step_lengths = np.sqrt(dx ** 2 + dy ** 2)
    velocities = step_lengths / time_interval_sec if len(step_lengths) else np.array([])
    total_path_length = float(step_lengths.sum())
    net_displacement = float(np.hypot(xs[-1] - xs[0], ys[-1] - ys[0]))
    straightness_index = net_displacement / total_path_length if total_path_length > 0 else 0.0
    directional_component = dx * direction_vec[0] + dy * direction_vec[1]
    flow_aligned_fraction = (
        float(np.mean(directional_component > 0)) if len(directional_component) else 0.0
    )
    cell_results.append(
        {
            "cell_id": int(particle_id),
            "n_frames": int(len(group)),
            "mean_velocity_um_per_s": float(np.mean(velocities)) if len(velocities) else 0.0,
            "total_path_length_um": total_path_length,
            "net_displacement_um": net_displacement,
            "straightness_index": float(straightness_index),
            "flow_aligned_fraction": flow_aligned_fraction,
        }
    )

summary = {
    "n_cells_tracked": len(cell_results),
    "mean_velocity_um_per_s": (
        float(np.mean([c["mean_velocity_um_per_s"] for c in cell_results]))
        if cell_results
        else 0.0
    ),
    "flow_direction": flow_direction,
    "method_disclaimer": (
        "General-purpose trackpy feature-detection + linking pipeline. Not clinically "
        "or publication validated; use only as a research-triage aid."
    ),
}
print(_json.dumps({"cells": cell_results, "summary": summary}))
"""

_CYTOKINE_PRODUCTION_SCRIPT = """
import os

import numpy as np
import flowio

fcs_files_dict = _args["fcs_files_dict"]
output_dir = "/workspace/" + _args["output_dir"]
os.makedirs(output_dir, exist_ok=True)


def load_fcs(relative_path):
    flow_data = flowio.FlowData("/workspace/" + relative_path)
    n_channels = flow_data.channel_count
    events = np.array(flow_data.events, dtype=float).reshape(-1, n_channels)
    channel_names = {}
    for idx_str, meta in flow_data.channels.items():
        name = meta.get("PnS") or meta.get("PnN") or idx_str
        channel_names[int(idx_str) - 1] = name
    return events, channel_names


def find_channel_index(channel_names, keyword):
    keyword = keyword.lower()
    for idx, name in channel_names.items():
        if keyword in name.lower():
            return idx
    return None


samples = {condition: load_fcs(path) for condition, path in fcs_files_dict.items()}

control_key = next(
    (
        k
        for k in samples
        if any(tag in k.lower() for tag in ("unstim", "control", "vehicle", "baseline"))
    ),
    next(iter(samples)),
)
control_events, control_channels = samples[control_key]

ifn_idx = find_channel_index(control_channels, "ifn")
il17_idx = find_channel_index(control_channels, "il-17")
if il17_idx is None:
    il17_idx = find_channel_index(control_channels, "il17")

if ifn_idx is None or il17_idx is None:
    raise ValueError(
        "Could not identify IFN-gamma / IL-17 fluorescence channels from FCS parameter "
        "labels (available channels: " + str(list(control_channels.values())) + ")."
    )

ifn_threshold = float(np.percentile(control_events[:, ifn_idx], 99))
il17_threshold = float(np.percentile(control_events[:, il17_idx], 99))

results_by_condition = {}
for condition, (events, _channels) in samples.items():
    n_total = events.shape[0]
    ifn_pos = events[:, ifn_idx] > ifn_threshold
    il17_pos = events[:, il17_idx] > il17_threshold
    results_by_condition[condition] = {
        "n_cells": int(n_total),
        "pct_ifn_gamma_pos": float(100.0 * np.sum(ifn_pos) / n_total) if n_total else 0.0,
        "pct_il17_pos": float(100.0 * np.sum(il17_pos) / n_total) if n_total else 0.0,
        "pct_double_positive": (
            float(100.0 * np.sum(ifn_pos & il17_pos) / n_total) if n_total else 0.0
        ),
    }

output = {
    "negative_control_condition": control_key,
    "ifn_gamma_threshold": ifn_threshold,
    "il17_threshold": il17_threshold,
    "results_by_condition": results_by_condition,
    "method_disclaimer": (
        "Gating uses a 99th-percentile threshold over the negative-control condition "
        "(general heuristic, not clinically or publication validated)."
    ),
}
print(_json.dumps(output))
"""

_EBV_ANTIBODY_TITERS_SCRIPT = """
import os

import numpy as np
from scipy.optimize import curve_fit

raw_od_data = _args["raw_od_data"]
standard_curve_data = _args["standard_curve_data"]
sample_metadata = _args.get("sample_metadata", {})
output_dir = "/workspace/" + _args["output_dir"]
os.makedirs(output_dir, exist_ok=True)

concentrations = np.array(standard_curve_data["concentrations"], dtype=float)
od_values = np.array(standard_curve_data["od_values"], dtype=float)


def four_param_logistic(x, a, b, c, d):
    x_safe = np.where(x <= 0, 1e-9, x)
    return d + (a - d) / (1.0 + (x_safe / c) ** b)


a0 = float(od_values.max())
d0 = float(od_values.min())
nonzero_conc = concentrations[concentrations > 0]
c0 = float(np.median(nonzero_conc)) if len(nonzero_conc) else 1.0
b0 = 1.0

popt, _pcov = curve_fit(
    four_param_logistic, concentrations, od_values, p0=[a0, b0, c0, d0], maxfev=10000
)
a, b, c, d = (float(v) for v in popt)

fitted = four_param_logistic(concentrations, a, b, c, d)
ss_res = float(np.sum((od_values - fitted) ** 2))
ss_tot = float(np.sum((od_values - od_values.mean()) ** 2))
r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else None


def invert_4pl(od):
    lo, hi = sorted((a, d))
    if od <= lo or od >= hi:
        return None
    ratio = (a - d) / (od - d) - 1.0
    if ratio <= 0:
        return None
    return float(c * ratio ** (1.0 / b))


titers = {}
for sample_id, od in raw_od_data.items():
    estimated_titer = invert_4pl(float(od))
    titers[sample_id] = {
        "od": float(od),
        "estimated_titer": estimated_titer,
        "in_range": estimated_titer is not None,
        "metadata": sample_metadata.get(sample_id, {}),
    }

result = {
    "fit_params": {"A": a, "B": b, "C": c, "D": d},
    "r_squared": r_squared,
    "titers": titers,
}
print(_json.dumps(result))
"""

_CNS_LESION_HISTOLOGY_SCRIPT = """
import os

import numpy as np
from skimage import color, filters, io, measure

image_path = "/workspace/" + _args["image_path"]
output_dir = "/workspace/" + _args["output_dir"]
stain_type = _args["stain_type"]

os.makedirs(output_dir, exist_ok=True)

img = io.imread(image_path)
if img.ndim == 2:
    img = color.gray2rgb(img)
img_rgb = img[..., :3]
total_pixels = img_rgb.shape[0] * img_rgb.shape[1]

gray = color.rgb2gray(img_rgb)
tissue_threshold = filters.threshold_otsu(gray)
tissue_mask = gray < tissue_threshold
tissue_pixels = int(np.sum(tissue_mask))
tissue_area_fraction = float(tissue_pixels / total_pixels) if total_pixels else 0.0

hed = color.rgb2hed(img_rgb)
hematoxylin = hed[..., 0]

hema_sample = hematoxylin[tissue_mask] if tissue_pixels else hematoxylin.flatten()
hema_threshold = filters.threshold_otsu(hema_sample)
infiltrate_mask = (hematoxylin > hema_threshold) & tissue_mask
infiltrate_fraction = float(np.sum(infiltrate_mask) / tissue_pixels) if tissue_pixels else 0.0

labeled = measure.label(infiltrate_mask)
regions = measure.regionprops(labeled)
infiltrate_focus_count = len([r for r in regions if r.area >= 10])

demyelination_index = None
if any(tag in stain_type.lower() for tag in ("lfb", "luxol", "myelin")):
    blue_channel = img_rgb[..., 2].astype(float) / 255.0
    mean_blue_in_tissue = float(np.mean(blue_channel[tissue_mask])) if tissue_pixels else 0.0
    demyelination_index = float(1.0 - mean_blue_in_tissue)

result = {
    "stain_type": stain_type,
    "tissue_area_fraction": tissue_area_fraction,
    "immune_infiltrate_area_fraction": infiltrate_fraction,
    "infiltrate_focus_count": infiltrate_focus_count,
    "demyelination_index": demyelination_index,
    "method_disclaimer": (
        "General-purpose color-deconvolution (Ruifrok & Johnston) + Otsu thresholding "
        "pipeline (scikit-image). Not clinically or publication validated; use only as "
        "a research-triage aid."
    ),
}
print(_json.dumps(result))
"""

_IHC_IMAGE_SCRIPT = """
import os

import numpy as np
from skimage import color, filters, io

image_path = "/workspace/" + _args["image_path"]
output_dir = "/workspace/" + _args["output_dir"]
protein_name = _args["protein_name"]

os.makedirs(output_dir, exist_ok=True)

img = io.imread(image_path)
if img.ndim == 2:
    img = color.gray2rgb(img)
img_rgb = img[..., :3]

gray = color.rgb2gray(img_rgb)
tissue_threshold = filters.threshold_otsu(gray)
tissue_mask = gray < tissue_threshold
tissue_pixels = int(np.sum(tissue_mask))

hed = color.rgb2hed(img_rgb)
dab_channel = hed[..., 2]  # DAB (brown chromogen) channel of the H-DAB deconvolution.

dab_sample = dab_channel[tissue_mask] if tissue_pixels else dab_channel.flatten()
dab_threshold = filters.threshold_otsu(dab_sample)
positive_mask = (dab_channel > dab_threshold) & tissue_mask
positive_pixels = int(np.sum(positive_mask))

percent_positive_area = float(100.0 * positive_pixels / tissue_pixels) if tissue_pixels else 0.0
mean_dab_optical_density = float(np.mean(dab_channel[tissue_mask])) if tissue_pixels else 0.0

if positive_pixels > 0:
    dab_positive_values = dab_channel[positive_mask]
    t1, t2 = np.percentile(dab_positive_values, [33.33, 66.67])
    weak = int(np.sum(dab_positive_values <= t1))
    moderate = int(np.sum((dab_positive_values > t1) & (dab_positive_values <= t2)))
    strong = int(np.sum(dab_positive_values > t2))
    h_score = float((1 * weak + 2 * moderate + 3 * strong) / tissue_pixels * 100.0)
else:
    weak = moderate = strong = 0
    h_score = 0.0

result = {
    "protein_name": protein_name,
    "tissue_area_pixels": tissue_pixels,
    "percent_positive_area": percent_positive_area,
    "mean_dab_optical_density": mean_dab_optical_density,
    "h_score": h_score,
    "intensity_breakdown": {"weak_1plus": weak, "moderate_2plus": moderate, "strong_3plus": strong},
    "method_disclaimer": (
        "General-purpose DAB color-deconvolution (Ruifrok & Johnston matrix via "
        "scikit-image rgb2hed) + Otsu thresholding, with a standard 3-tercile H-score. "
        "Not clinically or publication validated; use only as a research-triage aid."
    ),
}
print(_json.dumps(result))
"""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def isolate_purify_immune_cells(arguments: dict, driver) -> dict:
    """Tier A: generates a tissue-dissociation + MACS/FACS purification
    protocol (digestion buffer/temperature, RBC lysis, marker selection,
    purity QC) from established immunology methods. Deterministic text
    output, no numeric assay data is fabricated."""
    params = IsolateImmuneCellsArgs(**(arguments or {}))
    return run_in_sandbox(driver, script_body=_ISOLATE_PROTOCOL_SCRIPT, args=params.model_dump())


def track_immune_cells_under_flow(arguments: dict, driver) -> dict:
    """Tier C: trackpy-based feature detection + linking across a
    time-lapse image sequence of immune cells under laminar flow, reporting
    per-cell velocity/displacement/straightness and flow-alignment.
    General-purpose method, NOT clinically or publication validated."""
    params = ImmuneCellFlowTrackingArgs(**(arguments or {}))
    image_sequence_path = ensure_safe_relative_path(params.image_sequence_path)
    output_dir = ensure_safe_relative_path(params.output_dir)
    args = {
        "image_sequence_path": image_sequence_path,
        "output_dir": output_dir,
        "pixel_size_um": params.pixel_size_um,
        "time_interval_sec": params.time_interval_sec,
        "flow_direction": params.flow_direction,
    }
    return run_in_sandbox(driver, script_body=_TRACK_IMMUNE_CELLS_FLOW_SCRIPT, args=args)


def analyze_cytokine_production_in_cd4_tcells(arguments: dict, driver) -> dict:
    """Tier C: quantifies %IFN-gamma+/%IL-17+ (and double-positive) CD4 T
    cells per stimulation condition from raw FCS files, gating each
    condition against a 99th-percentile threshold derived from a detected
    negative-control condition. General-purpose method, NOT clinically or
    publication validated."""
    params = CytokineProductionArgs(**(arguments or {}))
    fcs_files_dict = {
        condition: ensure_safe_relative_path(path)
        for condition, path in params.fcs_files_dict.items()
    }
    output_dir = ensure_safe_relative_path(params.output_dir)
    args = {"fcs_files_dict": fcs_files_dict, "output_dir": output_dir}
    return run_in_sandbox(driver, script_body=_CYTOKINE_PRODUCTION_SCRIPT, args=args)


def analyze_ebv_antibody_titers(arguments: dict, driver) -> dict:
    """Tier B: fits a real 4-parameter logistic (4PL) curve to ELISA
    standard-curve data via `scipy.optimize.curve_fit`, then inverts the
    fitted curve in closed form to estimate an antibody titer for each raw
    OD reading (flagging readings outside the standard curve's dynamic
    range as out-of-range rather than extrapolating silently)."""
    params = EbvAntibodyTitersArgs(**(arguments or {}))
    output_dir = ensure_safe_relative_path(params.output_dir)
    args = {
        "raw_od_data": params.raw_od_data,
        "standard_curve_data": params.standard_curve_data,
        "sample_metadata": params.sample_metadata,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=_EBV_ANTIBODY_TITERS_SCRIPT, args=args)


def analyze_cns_lesion_histology(arguments: dict, driver) -> dict:
    """Tier C: quantifies immune-cell infiltration (hematoxylin-channel
    density via Ruifrok & Johnston color deconvolution) and, for
    myelin-specific stains (Luxol Fast Blue), a demyelination index from
    blue-channel intensity loss. General-purpose scikit-image method, NOT
    clinically or publication validated."""
    params = CnsLesionHistologyArgs(**(arguments or {}))
    image_path = ensure_safe_relative_path(params.image_path)
    output_dir = ensure_safe_relative_path(params.output_dir)
    args = {"image_path": image_path, "output_dir": output_dir, "stain_type": params.stain_type}
    return run_in_sandbox(driver, script_body=_CNS_LESION_HISTOLOGY_SCRIPT, args=args)


def analyze_immunohistochemistry_image(arguments: dict, driver) -> dict:
    """Tier C: quantifies IHC protein expression via DAB color
    deconvolution (Ruifrok & Johnston H-DAB matrix, `skimage.color.rgb2hed`)
    against tissue detected by Otsu thresholding, reporting percent-positive
    area, mean DAB optical density, and a standard 3-tercile H-score.
    General-purpose method, NOT clinically or publication validated."""
    params = IhcImageArgs(**(arguments or {}))
    image_path = ensure_safe_relative_path(params.image_path)
    output_dir = ensure_safe_relative_path(params.output_dir)
    args = {
        "image_path": image_path,
        "protein_name": params.protein_name,
        "output_dir": output_dir,
    }
    return run_in_sandbox(driver, script_body=_IHC_IMAGE_SCRIPT, args=args)


def register_immunology_tools(registry, driver) -> List[str]:
    """Registers every "Categoria: Imunologia" tool into `registry`, bound
    to `driver`'s sandbox. Returns the registered tool names."""
    handlers = {
        "isolate_purify_immune_cells": isolate_purify_immune_cells,
        "track_immune_cells_under_flow": track_immune_cells_under_flow,
        "analyze_cytokine_production_in_cd4_tcells": analyze_cytokine_production_in_cd4_tcells,
        "analyze_ebv_antibody_titers": analyze_ebv_antibody_titers,
        "analyze_cns_lesion_histology": analyze_cns_lesion_histology,
        "analyze_immunohistochemistry_image": analyze_immunohistochemistry_image,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, functools.partial(handler, driver=driver))
    return list(handlers.keys())
