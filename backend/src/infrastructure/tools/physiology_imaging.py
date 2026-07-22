"""Physiology / cardio / neuro / imaging action tools (Fase 5, "Categoria:
Fisiologia / cardio / neuro / imaging" of `backend/docs/tools/
action_tool_catalog.md`).

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

Tiering (this "Categoria" heading in the catalog carries NO aggregate tier
tag and none of its 18 bullet entries carry an inline tier tag either,
unlike sibling categories -- tiers below are derived directly from the
catalog's own A/B/C/D rubric at the top of `action_tool_catalog.md`):

- Tier A (deterministic real lib, no statistical model): `analyze_abr_
  waveform_p1_metrics` (scipy.signal peak detection against the documented
  ABR wave-identification convention -- first prominent peak in the
  waveform), `analyze_fatty_acid_composition_by_gc` (deterministic GC
  peak-area normalization + IUPAC `Cxx:y` nomenclature classification, no
  fitted model).
- Tier B (real numerical method -- curve_fit / ODE / closed-form formula,
  not a pretrained checkpoint): `perform_cosinor_analysis` (real cosinor
  least-squares regression, Nelson et al. formulation), `calculate_brain_
  adc_map` (per-voxel monoexponential S(b)=S0*exp(-b*ADC) fit via linear
  least squares on log-signal), `analyze_endolysosomal_calcium_dynamics`
  (scipy.optimize.curve_fit exponential decay), `analyze_hemodynamic_data`
  (scipy.signal peak/trough detection + closed-form MAP/HR formulas),
  `simulate_thyroid_hormone_pharmacokinetics` (real scipy.integrate.
  solve_ivp generic multi-compartment linear ODE -- see note below),
  `decode_behavior_from_neural_trajectories` (sklearn PCA + LinearRegression
  decoding).
- Tier C (real scikit-image/opencv/scipy.ndimage image processing, general
  purpose, NOT clinically/publication validated -- every one of these
  returns an explicit `method_disclaimer` field in its JSON result, not
  just a docstring note, so the disclaimer is actually visible to whatever
  LLM calls the tool, not only to a developer reading source):
  `analyze_aortic_diameter_and_geometry`, `analyze_thrombus_histology`,
  `analyze_intracellular_calcium_with_rhod2`, `quantify_corneal_nerve_
  fibers`, `segment_and_quantify_cells_in_multiplexed_images`,
  `analyze_bone_microct_morphometry`, `reconstruct_3d_face_from_mri`,
  `analyze_ciliary_beat_frequency`, `analyze_protein_colocalization`,
  `quantify_amyloid_beta_plaques`.
- Tier D: none. Nothing in this category needs a proprietary pretrained
  checkpoint or a GPU cluster, so this module never touches
  `backend/docs/tools/UNSUPPORTED.md`.

On `simulate_thyroid_hormone_pharmacokinetics`: the catalog's cross-cutting
notes ask several ODE tools to share one generic `scipy.integrate.solve_ivp`
building block instead of reimplementing the integrator per tool. That
shared helper (if/when centralized) would live in a sibling category's
module (`simulate_whole_cell_ode_model` is catalogued under "Synthetic
biology & systems biology", not this category) -- this module's own hard
rules forbid touching any `tools/*.py` file other than this one, and a
sandboxed `script_body` is a standalone script with no import access to
this backend's own source tree anyway (only the sandbox toolkit conda env).
So `simulate_thyroid_hormone_pharmacokinetics` below is a self-contained
implementation of the SAME pattern (a generic linear multi-compartment ODE
built from a `transfer_rates`/`elimination_rates`/`production_rates`
specification, integrated via `scipy.integrate.solve_ivp`), not a literal
cross-module import.

On `bmd_proxy_mean_intensity` (`analyze_bone_microct_morphometry`): a true
areal bone-mineral-density value requires a phantom-calibrated intensity-to-
density conversion this deployment does not have; rather than fabricate a
calibrated BMD number, that field is honestly labeled as an UNCALIBRATED
mean voxel intensity inside the segmented bone mask.

Every file-path-shaped argument (`image_path`, `video_path`,
`*_image_path`, `*_file_path`, `output_dir`, `output_file`, `output_path`,
`output_directory`, `mask_file_path`, `gc_data_file`) is passed through
`ensure_safe_relative_path` before being handed to the sandbox.
"""
import functools
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from src.domain.services.path_guard import ensure_safe_relative_path
from src.infrastructure.tools._sandbox_tool_base import run_in_sandbox


def _safe_optional_path(value: Optional[str]) -> Optional[str]:
    """Path-guards an optional file-path argument, passing `None` through
    unchanged (used for e.g. `mask_file_path`)."""
    return ensure_safe_relative_path(value) if value else None


# ---------------------------------------------------------------------------
# Argument models
# ---------------------------------------------------------------------------


class AorticDiameterArgs(BaseModel):
    """Args for `analyze_aortic_diameter_and_geometry` (Tier C)."""

    image_path: str = Field(..., min_length=1)
    output_dir: str = "./output"


class ThrombusHistologyArgs(BaseModel):
    """Args for `analyze_thrombus_histology` (Tier C)."""

    image_path: str = Field(..., min_length=1)
    output_dir: str = "./output"


class Rhod2CalciumArgs(BaseModel):
    """Args for `analyze_intracellular_calcium_with_rhod2` (Tier C)."""

    background_image_path: str = Field(..., min_length=1)
    control_image_path: str = Field(..., min_length=1)
    sample_image_path: str = Field(..., min_length=1)
    output_dir: str = "./output"


class CornealNerveFibersArgs(BaseModel):
    """Args for `quantify_corneal_nerve_fibers` (Tier C)."""

    image_path: str = Field(..., min_length=1)
    marker_type: str = Field(..., min_length=1)
    output_dir: str = "./output"
    threshold_method: str = Field("otsu", min_length=1)


class MultiplexedCellSegmentationArgs(BaseModel):
    """Args for `segment_and_quantify_cells_in_multiplexed_images` (Tier C)."""

    image_path: str = Field(..., min_length=1)
    markers_list: List[str] = Field(..., min_length=1)
    nuclear_channel_index: int = Field(0, ge=0)
    output_dir: str = "./output"


class BoneMicroctMorphometryArgs(BaseModel):
    """Args for `analyze_bone_microct_morphometry` (Tier C)."""

    input_file_path: str = Field(..., min_length=1)
    output_dir: str = "./results"
    threshold_value: Optional[float] = None


class Reconstruct3dFaceArgs(BaseModel):
    """Args for `reconstruct_3d_face_from_mri` (Tier C)."""

    mri_file_path: str = Field(..., min_length=1)
    output_dir: str = "./output"
    subject_id: str = Field("subject", min_length=1)
    threshold_value: int = 300


class AbrWaveformArgs(BaseModel):
    """Args for `analyze_abr_waveform_p1_metrics` (Tier A)."""

    time_ms: List[float] = Field(..., min_length=2)
    amplitude_uv: List[float] = Field(..., min_length=2)

    @model_validator(mode="after")
    def _equal_length(self) -> "AbrWaveformArgs":
        if len(self.time_ms) != len(self.amplitude_uv):
            raise ValueError("time_ms and amplitude_uv must be the same length.")
        return self


class CiliaryBeatFrequencyArgs(BaseModel):
    """Args for `analyze_ciliary_beat_frequency` (Tier C)."""

    video_path: str = Field(..., min_length=1)
    roi_count: int = Field(5, gt=0, le=500)
    min_freq: float = Field(0.0, ge=0)
    max_freq: float = Field(30.0, gt=0)
    output_dir: str = "./"

    @model_validator(mode="after")
    def _validate_freq_range(self) -> "CiliaryBeatFrequencyArgs":
        if self.max_freq <= self.min_freq:
            raise ValueError("max_freq must be greater than min_freq.")
        return self


class ProteinColocalizationArgs(BaseModel):
    """Args for `analyze_protein_colocalization` (Tier C)."""

    channel1_path: str = Field(..., min_length=1)
    channel2_path: str = Field(..., min_length=1)
    output_dir: str = "./output"
    threshold_method: str = Field("otsu", min_length=1)


class CosinorAnalysisArgs(BaseModel):
    """Args for `perform_cosinor_analysis` (Tier B)."""

    time_data: List[float] = Field(..., min_length=4)
    physiological_data: List[float] = Field(..., min_length=4)
    period: float = Field(24.0, gt=0)

    @model_validator(mode="after")
    def _equal_length(self) -> "CosinorAnalysisArgs":
        if len(self.time_data) != len(self.physiological_data):
            raise ValueError("time_data and physiological_data must be the same length.")
        return self


class BrainAdcMapArgs(BaseModel):
    """Args for `calculate_brain_adc_map` (Tier B)."""

    dwi_file_path: str = Field(..., min_length=1)
    b_values: List[float] = Field(..., min_length=2)
    output_path: str = "adc_map.nii.gz"
    mask_file_path: Optional[str] = None


class EndolysosomalCalciumArgs(BaseModel):
    """Args for `analyze_endolysosomal_calcium_dynamics` (Tier B)."""

    time_points: List[float] = Field(..., min_length=3)
    luminescence_values: List[float] = Field(..., min_length=3)
    treatment_time: Optional[float] = None
    cell_type: Optional[str] = None
    treatment_name: Optional[str] = None
    output_file: str = "calcium_analysis_results.txt"

    @model_validator(mode="after")
    def _equal_length(self) -> "EndolysosomalCalciumArgs":
        if len(self.time_points) != len(self.luminescence_values):
            raise ValueError("time_points and luminescence_values must be the same length.")
        return self


class FattyAcidGcArgs(BaseModel):
    """Args for `analyze_fatty_acid_composition_by_gc` (Tier A)."""

    gc_data_file: str = Field(..., min_length=1)
    tissue_type: str = Field(..., min_length=1)
    sample_id: str = Field(..., min_length=1)
    output_directory: str = "./results"


class HemodynamicDataArgs(BaseModel):
    """Args for `analyze_hemodynamic_data` (Tier B)."""

    pressure_data: List[float] = Field(..., min_length=3)
    sampling_rate: float = Field(..., gt=0)
    output_file: str = "hemodynamic_results.csv"


class ThyroidPkArgs(BaseModel):
    """Args for `simulate_thyroid_hormone_pharmacokinetics` (Tier B). See
    the module docstring for `parameters`'s expected shape: optional
    `transfer_rates` (dict of `"source->destination"` -> rate constant),
    `elimination_rates` (dict of compartment -> rate constant), and
    `production_rates` (dict of compartment -> zero-order input rate)."""

    parameters: Dict[str, Any] = Field(default_factory=dict)
    initial_conditions: Dict[str, float] = Field(..., min_length=1)
    time_span: Tuple[float, float] = (0.0, 24.0)
    time_points: int = Field(100, gt=1, le=100000)

    @model_validator(mode="after")
    def _validate_time_span(self) -> "ThyroidPkArgs":
        if self.time_span[1] <= self.time_span[0]:
            raise ValueError("time_span end must be greater than time_span start.")
        return self


class AmyloidPlaquesArgs(BaseModel):
    """Args for `quantify_amyloid_beta_plaques` (Tier C)."""

    image_path: str = Field(..., min_length=1)
    output_dir: str = "./results"
    threshold_method: str = Field("otsu", min_length=1)
    min_plaque_size: int = Field(50, gt=0)
    manual_threshold: int = Field(127, ge=0)


class DecodeNeuralTrajectoriesArgs(BaseModel):
    """Args for `decode_behavior_from_neural_trajectories` (Tier B). Note:
    `behavioral_data` models a single behavioral variable per call (a 1-D
    array aligned with `neural_data`'s rows) -- call once per behavioral
    variable of interest for a multi-variable decoding study."""

    neural_data: List[List[float]] = Field(..., min_length=2)
    behavioral_data: List[float] = Field(..., min_length=2)
    n_components: int = Field(10, gt=0)
    output_dir: str = "./results"

    @model_validator(mode="after")
    def _validate_shapes(self) -> "DecodeNeuralTrajectoriesArgs":
        if len(self.neural_data) != len(self.behavioral_data):
            raise ValueError(
                "neural_data and behavioral_data must have the same number of samples (rows)."
            )
        row_lengths = {len(row) for row in self.neural_data}
        if len(row_lengths) != 1:
            raise ValueError("neural_data rows must all have the same number of features.")
        return self


# ---------------------------------------------------------------------------
# Script bodies (each is a standalone script run inside the bwrap sandbox --
# no imports from this backend's own source tree, only the sandbox
# toolkit's conda env; each reads `_args`, computed by run_in_sandbox's own
# preamble, and prints exactly one trailing line of JSON).
# ---------------------------------------------------------------------------

_AORTIC_DIAMETER_SCRIPT = """
import os

import numpy as np
from skimage import color, filters, io, measure, morphology

image_path = "/workspace/" + _args["image_path"]
output_dir = "/workspace/" + _args["output_dir"]
os.makedirs(output_dir, exist_ok=True)

pixel_spacing_mm = None
if image_path.lower().endswith((".dcm", ".dicom")):
    import pydicom

    ds = pydicom.dcmread(image_path)
    img = ds.pixel_array.astype(float)
    spacing = getattr(ds, "PixelSpacing", None)
    if spacing:
        pixel_spacing_mm = float(spacing[0])
else:
    img = io.imread(image_path)
    if img.ndim == 3:
        img = color.rgb2gray(img[..., :3])
    img = img.astype(float)

img_range = img.max() - img.min()
img_norm = (img - img.min()) / img_range if img_range else img
threshold = filters.threshold_otsu(img_norm)
mask = img_norm > threshold
mask = morphology.remove_small_objects(mask, min_size=50)
labeled = measure.label(mask)
regions = measure.regionprops(labeled)
if not regions:
    raise ValueError("No candidate aortic lumen region found after Otsu segmentation.")
largest = max(regions, key=lambda r: r.area)

scale = pixel_spacing_mm if pixel_spacing_mm else 1.0
unit = "mm" if pixel_spacing_mm else "px"

result = {
    "equivalent_diameter": float(largest.equivalent_diameter) * scale,
    "major_axis_length": float(largest.major_axis_length) * scale,
    "minor_axis_length": float(largest.minor_axis_length) * scale,
    "area": float(largest.area) * (scale ** 2),
    "perimeter": float(largest.perimeter) * scale,
    "eccentricity": float(largest.eccentricity),
    "orientation_deg": float(np.degrees(largest.orientation)),
    "centroid": [float(c) for c in largest.centroid],
    "units": unit,
    "method_disclaimer": (
        "General-purpose Otsu-threshold + largest-connected-component geometry "
        "(scikit-image). Not clinically or publication validated."
    ),
}
print(_json.dumps(result))
"""

_THROMBUS_HISTOLOGY_SCRIPT = """
import os

import numpy as np
from skimage import color, filters, io

image_path = "/workspace/" + _args["image_path"]
output_dir = "/workspace/" + _args["output_dir"]
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

hed = color.rgb2hed(img_rgb)
hematoxylin = hed[..., 0]
eosin = hed[..., 1]

hema_sample = hematoxylin[tissue_mask] if tissue_pixels else hematoxylin.flatten()
eosin_sample = eosin[tissue_mask] if tissue_pixels else eosin.flatten()
hema_thresh = filters.threshold_otsu(hema_sample)
eosin_thresh = filters.threshold_otsu(eosin_sample)

leukocyte_rich_mask = (hematoxylin > hema_thresh) & tissue_mask
rbc_rich_mask = (eosin > eosin_thresh) & tissue_mask & ~leukocyte_rich_mask
fibrin_platelet_mask = tissue_mask & ~leukocyte_rich_mask & ~rbc_rich_mask


def frac(component_mask):
    return float(np.sum(component_mask) / tissue_pixels) if tissue_pixels else 0.0


result = {
    "tissue_area_fraction": float(tissue_pixels / total_pixels) if total_pixels else 0.0,
    "rbc_rich_fraction": frac(rbc_rich_mask),
    "fibrin_platelet_rich_fraction": frac(fibrin_platelet_mask),
    "leukocyte_rich_fraction": frac(leukocyte_rich_mask),
    "method_disclaimer": (
        "General-purpose H&E color-deconvolution (Ruifrok & Johnston) + Otsu-threshold "
        "component classification (scikit-image). Not clinically or publication validated."
    ),
}
print(_json.dumps(result))
"""

_RHOD2_CALCIUM_SCRIPT = """
import os

import numpy as np
from skimage import color, io


def load_gray(path):
    img = io.imread(path)
    if img.ndim == 3:
        img = color.rgb2gray(img[..., :3])
    return img.astype(float)


background_path = "/workspace/" + _args["background_image_path"]
control_path = "/workspace/" + _args["control_image_path"]
sample_path = "/workspace/" + _args["sample_image_path"]
output_dir = "/workspace/" + _args["output_dir"]
os.makedirs(output_dir, exist_ok=True)

background = load_gray(background_path)
control = load_gray(control_path)
sample = load_gray(sample_path)

background_mean = float(np.mean(background))
control_corrected_mean = float(np.mean(control) - background_mean)
sample_corrected_mean = float(np.mean(sample) - background_mean)

ratio = (
    sample_corrected_mean / control_corrected_mean if control_corrected_mean != 0 else None
)

result = {
    "background_mean_intensity": background_mean,
    "control_mean_intensity_corrected": control_corrected_mean,
    "sample_mean_intensity_corrected": sample_corrected_mean,
    "f_over_f0_ratio": ratio,
    "method_disclaimer": (
        "General-purpose background-subtracted mean-intensity ratio (Rhod-2 F/F0 proxy). "
        "Not clinically or publication validated."
    ),
}
print(_json.dumps(result))
"""

_CORNEAL_NERVE_FIBERS_SCRIPT = """
import os

import numpy as np
from scipy.ndimage import convolve
from skimage import color, filters, io, measure, morphology

image_path = "/workspace/" + _args["image_path"]
output_dir = "/workspace/" + _args["output_dir"]
marker_type = _args["marker_type"]
threshold_method = _args["threshold_method"]
os.makedirs(output_dir, exist_ok=True)

img = io.imread(image_path)
if img.ndim == 3:
    img = color.rgb2gray(img[..., :3])
img = img.astype(float)

threshold_func = getattr(filters, "threshold_" + threshold_method, None)
if threshold_func is None:
    raise ValueError(f"Unsupported threshold_method: {threshold_method!r}")
thresh = float(threshold_func(img))

mask = img > thresh
mask = morphology.remove_small_objects(mask, min_size=15)
skeleton = morphology.skeletonize(mask)

total_area_px = img.shape[0] * img.shape[1]
fiber_length_px = int(np.sum(skeleton))
fiber_density = float(fiber_length_px / total_area_px) if total_area_px else 0.0

neighbor_kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])
neighbor_count = convolve(skeleton.astype(int), neighbor_kernel, mode="constant")
branch_point_count = int(np.sum(skeleton & (neighbor_count >= 3)))

labeled_fibers = measure.label(skeleton, connectivity=2)
fiber_segment_count = int(labeled_fibers.max())

result = {
    "marker_type": marker_type,
    "threshold_method": threshold_method,
    "threshold_value_used": thresh,
    "fiber_length_px": fiber_length_px,
    "fiber_density_per_px2": fiber_density,
    "branch_point_count": branch_point_count,
    "fiber_segment_count": fiber_segment_count,
    "method_disclaimer": (
        "General-purpose threshold + skeletonization nerve-fiber quantification "
        "(scikit-image). Not clinically or publication validated."
    ),
}
print(_json.dumps(result))
"""

_MULTIPLEXED_CELL_SEGMENTATION_SCRIPT = """
import os

import numpy as np
from scipy import ndimage as ndi
from skimage import filters, io, measure, segmentation

image_path = "/workspace/" + _args["image_path"]
output_dir = "/workspace/" + _args["output_dir"]
markers_list = _args["markers_list"]
nuclear_channel_index = _args["nuclear_channel_index"]
os.makedirs(output_dir, exist_ok=True)

img = io.imread(image_path)
if img.ndim != 3:
    raise ValueError(
        "Expected a multichannel image with 3 dimensions "
        "(channels x H x W, or H x W x channels)."
    )
if img.shape[0] <= 8 and img.shape[0] < img.shape[-1]:
    channels = img.astype(float)
else:
    channels = np.moveaxis(img, -1, 0).astype(float)

n_channels = channels.shape[0]
if nuclear_channel_index >= n_channels:
    raise ValueError(
        f"nuclear_channel_index {nuclear_channel_index} out of range for {n_channels} channels."
    )
if len(markers_list) != n_channels:
    raise ValueError(
        f"markers_list length ({len(markers_list)}) must match the number of image "
        f"channels ({n_channels}); markers_list[i] names channel i (including the "
        "nuclear channel)."
    )

nuclear = channels[nuclear_channel_index]
nuclear_thresh = filters.threshold_otsu(nuclear)
nuclear_mask = nuclear > nuclear_thresh

distance = ndi.distance_transform_edt(nuclear_mask)
local_maxima = (ndi.maximum_filter(distance, size=7) == distance) & nuclear_mask
seed_markers, _ = ndi.label(local_maxima)
labels = segmentation.watershed(-distance, seed_markers, mask=nuclear_mask)

cell_count = int(labels.max())

marker_summary = {}
for idx, marker_name in enumerate(markers_list):
    if idx == nuclear_channel_index:
        continue
    channel = channels[idx]
    channel_thresh = float(filters.threshold_otsu(channel)) if cell_count else 0.0
    if cell_count:
        per_cell_mean = ndi.mean(channel, labels=labels, index=np.arange(1, cell_count + 1))
        per_cell_mean = np.atleast_1d(per_cell_mean)
        positive_cells = int(np.sum(per_cell_mean > channel_thresh))
        mean_intensity_all_cells = float(np.mean(per_cell_mean))
    else:
        positive_cells = 0
        mean_intensity_all_cells = 0.0
    marker_summary[marker_name] = {
        "positive_cell_count": positive_cells,
        "positive_fraction": float(positive_cells / cell_count) if cell_count else 0.0,
        "mean_intensity_all_cells": mean_intensity_all_cells,
    }

result = {
    "cell_count": cell_count,
    "nuclear_channel_index": nuclear_channel_index,
    "nuclear_marker_name": markers_list[nuclear_channel_index],
    "marker_summary": marker_summary,
    "method_disclaimer": (
        "General-purpose Otsu-threshold nuclear watershed segmentation + per-cell "
        "marker-intensity thresholding (scikit-image/scipy.ndimage). Not clinically or "
        "publication validated."
    ),
}
print(_json.dumps(result))
"""

_BONE_MICROCT_MORPHOMETRY_SCRIPT = """
import os

import nibabel as nib
import numpy as np
from skimage import filters, measure

input_file_path = "/workspace/" + _args["input_file_path"]
output_dir = "/workspace/" + _args["output_dir"]
threshold_value = _args["threshold_value"]
os.makedirs(output_dir, exist_ok=True)

img_nii = nib.load(input_file_path)
volume = img_nii.get_fdata()
zooms = img_nii.header.get_zooms()[:3]
voxel_volume_mm3 = float(zooms[0] * zooms[1] * zooms[2])

if threshold_value is None:
    threshold_value = float(filters.threshold_otsu(volume))
else:
    threshold_value = float(threshold_value)

bone_mask = volume > threshold_value
bv_voxels = int(np.sum(bone_mask))
tv_voxels = int(volume.size)
bv_tv = float(bv_voxels / tv_voxels) if tv_voxels else 0.0

try:
    verts, faces, _normals, _values = measure.marching_cubes(
        bone_mask.astype(float), level=0.5, spacing=zooms
    )
    triangles = verts[faces]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    bone_surface_area_mm2 = float(0.5 * np.sum(np.linalg.norm(cross, axis=1)))
except (ValueError, RuntimeError):
    bone_surface_area_mm2 = 0.0

total_volume_mm3 = tv_voxels * voxel_volume_mm3
bone_volume_mm3 = bv_voxels * voxel_volume_mm3

bs_tv = bone_surface_area_mm2 / total_volume_mm3 if total_volume_mm3 else 0.0
tb_th_mm = (2.0 * bv_tv / bs_tv) if bs_tv else None
tb_sp_mm = (2.0 * (1.0 - bv_tv) / bs_tv) if bs_tv else None
tb_n_per_mm = (bv_tv / tb_th_mm) if tb_th_mm else None

bmd_proxy = float(np.mean(volume[bone_mask])) if bv_voxels else 0.0

result = {
    "threshold_value": threshold_value,
    "bv_tv_fraction": bv_tv,
    "bone_volume_mm3": bone_volume_mm3,
    "total_volume_mm3": total_volume_mm3,
    "bone_surface_area_mm2": bone_surface_area_mm2,
    "tb_th_mm": tb_th_mm,
    "tb_sp_mm": tb_sp_mm,
    "tb_n_per_mm": tb_n_per_mm,
    "bmd_proxy_mean_intensity": bmd_proxy,
    "method_disclaimer": (
        "General-purpose threshold + marching-cubes Parfitt plate-model stereology "
        "(scikit-image/nibabel). 'bmd_proxy_mean_intensity' is an UNCALIBRATED mean voxel "
        "intensity within the bone mask, not a phantom-calibrated areal BMD. Not "
        "clinically or publication validated."
    ),
}
print(_json.dumps(result))
"""

_RECONSTRUCT_3D_FACE_SCRIPT = """
import os

import nibabel as nib
from skimage import measure

mri_file_path = "/workspace/" + _args["mri_file_path"]
output_dir = "/workspace/" + _args["output_dir"]
subject_id = _args["subject_id"]
threshold_value = float(_args["threshold_value"])
os.makedirs(output_dir, exist_ok=True)

img_nii = nib.load(mri_file_path)
volume = img_nii.get_fdata()
zooms = img_nii.header.get_zooms()[:3]

verts, faces, _normals, _values = measure.marching_cubes(
    volume, level=threshold_value, spacing=zooms
)

obj_path = os.path.join(output_dir, subject_id + ".obj")
with open(obj_path, "w", encoding="utf-8") as fh:
    for v in verts:
        fh.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\\n")
    for face in faces:
        fh.write(f"f {face[0] + 1} {face[1] + 1} {face[2] + 1}\\n")

bbox_mm = (verts.max(axis=0) - verts.min(axis=0)).tolist()

result = {
    "subject_id": subject_id,
    "output_mesh_path": obj_path.replace("/workspace/", "", 1),
    "vertex_count": int(verts.shape[0]),
    "face_count": int(faces.shape[0]),
    "threshold_value": threshold_value,
    "bounding_box_mm": [float(x) for x in bbox_mm],
    "method_disclaimer": (
        "General-purpose marching-cubes isosurface extraction (scikit-image) at a fixed "
        "intensity threshold. Not clinically or publication validated; not a diagnostic "
        "facial-reconstruction tool."
    ),
}
print(_json.dumps(result))
"""

_ABR_WAVEFORM_SCRIPT = """
import numpy as np
from scipy.signal import find_peaks

time_ms = np.array(_args["time_ms"], dtype=float)
amplitude_uv = np.array(_args["amplitude_uv"], dtype=float)

n_baseline = max(1, len(amplitude_uv) // 10)
baseline_uv = float(np.mean(amplitude_uv[:n_baseline]))
corrected = amplitude_uv - baseline_uv

span = corrected.max() - corrected.min()
peaks, _properties = find_peaks(corrected, prominence=0.05 * span if span else None)
p1_index = int(peaks[0]) if len(peaks) else int(np.argmax(corrected))

result = {
    "p1_latency_ms": float(time_ms[p1_index]),
    "p1_amplitude_uv": float(amplitude_uv[p1_index]),
    "p1_amplitude_from_baseline_uv": float(corrected[p1_index]),
    "baseline_uv": baseline_uv,
}
print(_json.dumps(result))
"""

_CILIARY_BEAT_FREQUENCY_SCRIPT = """
import os

import cv2
import numpy as np

video_path = "/workspace/" + _args["video_path"]
output_dir = "/workspace/" + _args["output_dir"]
roi_count = int(_args["roi_count"])
min_freq = float(_args["min_freq"])
max_freq = float(_args["max_freq"])
os.makedirs(output_dir, exist_ok=True)

capture = cv2.VideoCapture(video_path)
if not capture.isOpened():
    raise ValueError(f"Could not open video file: {video_path}")

fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
frames = []
while True:
    ok, frame = capture.read()
    if not ok:
        break
    frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(float))
capture.release()

if len(frames) < 4:
    raise ValueError("Video must contain at least 4 frames for FFT-based beat-frequency analysis.")

stack = np.stack(frames, axis=0)
height, width = stack.shape[1:]
grid_side = int(np.ceil(np.sqrt(roi_count)))
roi_h = max(1, height // grid_side)
roi_w = max(1, width // grid_side)

roi_frequencies = []
count = 0
for row in range(grid_side):
    for col in range(grid_side):
        if count >= roi_count:
            break
        y0, y1 = row * roi_h, min(height, (row + 1) * roi_h)
        x0, x1 = col * roi_w, min(width, (col + 1) * roi_w)
        roi_signal = stack[:, y0:y1, x0:x1].mean(axis=(1, 2))
        roi_signal = roi_signal - roi_signal.mean()
        spectrum = np.abs(np.fft.rfft(roi_signal))
        freqs = np.fft.rfftfreq(len(roi_signal), d=1.0 / fps)
        band = (freqs >= min_freq) & (freqs <= max_freq) & (freqs > 0)
        dominant_freq = float(freqs[band][np.argmax(spectrum[band])]) if np.any(band) else None
        roi_frequencies.append(dominant_freq)
        count += 1

valid = [f for f in roi_frequencies if f is not None]
result = {
    "fps": float(fps),
    "roi_count": len(roi_frequencies),
    "roi_beat_frequencies_hz": roi_frequencies,
    "mean_beat_frequency_hz": float(np.mean(valid)) if valid else None,
    "std_beat_frequency_hz": float(np.std(valid)) if valid else None,
    "method_disclaimer": (
        "General-purpose grid-ROI mean-intensity FFT dominant-frequency estimation "
        "(opencv/numpy). Not clinically or publication validated."
    ),
}
print(_json.dumps(result))
"""

_PROTEIN_COLOCALIZATION_SCRIPT = """
import os

import numpy as np
from scipy.stats import pearsonr
from skimage import color, filters, io

channel1_path = "/workspace/" + _args["channel1_path"]
channel2_path = "/workspace/" + _args["channel2_path"]
output_dir = "/workspace/" + _args["output_dir"]
threshold_method = _args["threshold_method"]
os.makedirs(output_dir, exist_ok=True)


def load_gray(path):
    img = io.imread(path)
    if img.ndim == 3:
        img = color.rgb2gray(img[..., :3])
    return img.astype(float)


channel1 = load_gray(channel1_path)
channel2 = load_gray(channel2_path)
if channel1.shape != channel2.shape:
    raise ValueError("channel1_path and channel2_path images must have the same dimensions.")

pearson_r, pearson_p = pearsonr(channel1.flatten(), channel2.flatten())

threshold_func = getattr(filters, "threshold_" + threshold_method, None)
if threshold_func is None:
    raise ValueError(f"Unsupported threshold_method: {threshold_method!r}")
t1 = float(threshold_func(channel1))
t2 = float(threshold_func(channel2))

mask1 = channel1 > t1
mask2 = channel2 > t2

sum_ch1 = float(np.sum(channel1))
sum_ch2 = float(np.sum(channel2))
manders_m1 = float(np.sum(channel1[mask2]) / sum_ch1) if sum_ch1 else 0.0
manders_m2 = float(np.sum(channel2[mask1]) / sum_ch2) if sum_ch2 else 0.0

result = {
    "pearson_r": float(pearson_r),
    "pearson_p_value": float(pearson_p),
    "manders_m1": manders_m1,
    "manders_m2": manders_m2,
    "threshold_method": threshold_method,
    "method_disclaimer": (
        "General-purpose Pearson correlation + Manders M1/M2 colocalization coefficients "
        "(scipy/scikit-image). Not clinically or publication validated."
    ),
}
print(_json.dumps(result))
"""

_COSINOR_ANALYSIS_SCRIPT = """
import numpy as np

time_data = np.array(_args["time_data"], dtype=float)
physiological_data = np.array(_args["physiological_data"], dtype=float)
period = float(_args["period"])

omega = 2.0 * np.pi / period
design = np.column_stack(
    [np.ones_like(time_data), np.cos(omega * time_data), np.sin(omega * time_data)]
)
beta, _residuals, _rank, _singular_values = np.linalg.lstsq(
    design, physiological_data, rcond=None
)
mesor, beta_cos, beta_sin = (float(b) for b in beta)

amplitude = float(np.sqrt(beta_cos ** 2 + beta_sin ** 2))
acrophase_rad = float(np.arctan2(-beta_sin, beta_cos))
acrophase_hours = float((-acrophase_rad / omega) % period)

fitted = design @ beta
ss_res = float(np.sum((physiological_data - fitted) ** 2))
ss_tot = float(np.sum((physiological_data - physiological_data.mean()) ** 2))
r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else None

result = {
    "mesor": mesor,
    "amplitude": amplitude,
    "acrophase_radians": acrophase_rad,
    "acrophase_hours": acrophase_hours,
    "period": period,
    "r_squared": r_squared,
}
print(_json.dumps(result))
"""

_BRAIN_ADC_MAP_SCRIPT = """
import os

import nibabel as nib
import numpy as np

dwi_file_path = "/workspace/" + _args["dwi_file_path"]
output_path = "/workspace/" + _args["output_path"]
mask_file_path = _args.get("mask_file_path")
b_values = np.array(_args["b_values"], dtype=float)

os.makedirs(os.path.dirname(output_path) or "/workspace", exist_ok=True)

dwi_img = nib.load(dwi_file_path)
dwi_data = dwi_img.get_fdata()
if dwi_data.ndim != 4:
    raise ValueError(f"Expected a 4D DWI volume (X,Y,Z,N); got shape {dwi_data.shape}.")
if dwi_data.shape[-1] != len(b_values):
    raise ValueError(
        f"DWI volume's last dimension ({dwi_data.shape[-1]}) must match the number of "
        f"b_values ({len(b_values)})."
    )

mask = None
if mask_file_path:
    mask_img = nib.load("/workspace/" + mask_file_path)
    mask = mask_img.get_fdata() > 0

signal = np.clip(dwi_data, 1e-6, None)
log_signal = signal.reshape(-1, len(b_values)).T
log_signal = np.log(log_signal)

design = np.column_stack([np.ones_like(b_values), -b_values])
coeffs, _residuals, _rank, _sv = np.linalg.lstsq(design, log_signal, rcond=None)
adc_map = coeffs[1].reshape(dwi_data.shape[:-1])

if mask is not None:
    adc_map = np.where(mask, adc_map, 0.0)
    valid_values = adc_map[mask]
else:
    valid_values = adc_map.flatten()

nib.save(nib.Nifti1Image(adc_map.astype(np.float32), dwi_img.affine), output_path)

result = {
    "output_path": output_path.replace("/workspace/", "", 1),
    "mean_adc": float(np.mean(valid_values)) if valid_values.size else None,
    "median_adc": float(np.median(valid_values)) if valid_values.size else None,
    "std_adc": float(np.std(valid_values)) if valid_values.size else None,
    "b_values": [float(b) for b in b_values],
    "voxel_count": int(valid_values.size),
}
print(_json.dumps(result))
"""

_ENDOLYSOSOMAL_CALCIUM_SCRIPT = """
import os

import numpy as np
from scipy.optimize import curve_fit

time_points = np.array(_args["time_points"], dtype=float)
luminescence_values = np.array(_args["luminescence_values"], dtype=float)
treatment_time = _args.get("treatment_time")
cell_type = _args.get("cell_type")
treatment_name = _args.get("treatment_name")
output_file = "/workspace/" + _args["output_file"]
os.makedirs(os.path.dirname(output_file) or "/workspace", exist_ok=True)

if treatment_time is not None:
    baseline_mask = time_points < treatment_time
else:
    n_baseline = max(1, len(time_points) // 10)
    baseline_mask = np.zeros_like(time_points, dtype=bool)
    baseline_mask[:n_baseline] = True

baseline = (
    float(np.mean(luminescence_values[baseline_mask]))
    if np.any(baseline_mask)
    else float(luminescence_values[0])
)

post_mask = ~baseline_mask
if np.any(post_mask):
    post_time = time_points[post_mask]
    post_values = luminescence_values[post_mask]
else:
    post_time = time_points
    post_values = luminescence_values

peak_idx = int(np.argmax(post_values))
peak_value = float(post_values[peak_idx])
peak_time = float(post_time[peak_idx])

decay_tau = None
decay_half_life = None
decay_time = time_points[time_points >= peak_time]
decay_values = luminescence_values[time_points >= peak_time]
if len(decay_time) >= 3:
    decay_t0 = decay_time[0]

    def exp_decay(t, amplitude, k, offset):
        return amplitude * np.exp(-k * (t - decay_t0)) + offset

    try:
        popt, _pcov = curve_fit(
            exp_decay,
            decay_time,
            decay_values,
            p0=[peak_value - baseline, 0.1, baseline],
            maxfev=5000,
        )
        k = float(popt[1])
        if k > 0:
            decay_tau = 1.0 / k
            decay_half_life = float(np.log(2) / k)
    except RuntimeError:
        pass

result = {
    "baseline": baseline,
    "peak_value": peak_value,
    "peak_time": peak_time,
    "peak_amplitude_above_baseline": peak_value - baseline,
    "decay_tau": decay_tau,
    "decay_half_life": decay_half_life,
    "cell_type": cell_type,
    "treatment_name": treatment_name,
}
with open(output_file, "w", encoding="utf-8") as fh:
    fh.write(_json.dumps(result, indent=2))
print(_json.dumps(result))
"""

_FATTY_ACID_GC_SCRIPT = """
import csv
import os
import re

gc_data_file = "/workspace/" + _args["gc_data_file"]
output_directory = "/workspace/" + _args["output_directory"]
tissue_type = _args["tissue_type"]
sample_id = _args["sample_id"]
os.makedirs(output_directory, exist_ok=True)

rows = []
with open(gc_data_file, newline="", encoding="utf-8") as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        name = (row.get("fatty_acid") or row.get("compound") or row.get("name") or "").strip()
        area_raw = row.get("peak_area") or row.get("area")
        if not name or area_raw in (None, ""):
            continue
        rows.append((name, float(area_raw)))

if not rows:
    raise ValueError(
        f"No usable rows found in {gc_data_file!r}; expected a CSV with a "
        "'fatty_acid'/'compound'/'name' column and a 'peak_area'/'area' column."
    )

total_area = sum(area for _name, area in rows)

_CXX_Y_RE = re.compile(r"C(\\d+):(\\d+)")


def classify(name):
    match = _CXX_Y_RE.search(name)
    if not match:
        return "unclassified"
    double_bonds = int(match.group(2))
    if double_bonds == 0:
        return "saturated"
    if double_bonds == 1:
        return "monounsaturated"
    return "polyunsaturated"


composition = []
class_totals = {"saturated": 0.0, "monounsaturated": 0.0, "polyunsaturated": 0.0, "unclassified": 0.0}
for name, area in rows:
    percent = 100.0 * area / total_area if total_area else 0.0
    fa_class = classify(name)
    class_totals[fa_class] += percent
    composition.append(
        {"fatty_acid": name, "peak_area": area, "percent_composition": percent, "class": fa_class}
    )
composition.sort(key=lambda c: c["percent_composition"], reverse=True)

output_csv = os.path.join(output_directory, sample_id + "_fatty_acid_composition.csv")
with open(output_csv, "w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=["fatty_acid", "peak_area", "percent_composition", "class"])
    writer.writeheader()
    writer.writerows(composition)

result = {
    "sample_id": sample_id,
    "tissue_type": tissue_type,
    "total_peak_area": total_area,
    "composition": composition,
    "class_totals_percent": class_totals,
    "output_csv": output_csv.replace("/workspace/", "", 1),
}
print(_json.dumps(result))
"""

_HEMODYNAMIC_DATA_SCRIPT = """
import csv
import os

import numpy as np
from scipy.signal import find_peaks

pressure_data = np.array(_args["pressure_data"], dtype=float)
sampling_rate = float(_args["sampling_rate"])
output_file = "/workspace/" + _args["output_file"]
os.makedirs(os.path.dirname(output_file) or "/workspace", exist_ok=True)

min_distance = max(1, int(sampling_rate * 0.3))
systolic_idx, _props1 = find_peaks(pressure_data, distance=min_distance)
diastolic_idx, _props2 = find_peaks(-pressure_data, distance=min_distance)

systolic_values = pressure_data[systolic_idx] if len(systolic_idx) else np.array([pressure_data.max()])
diastolic_values = pressure_data[diastolic_idx] if len(diastolic_idx) else np.array([pressure_data.min()])

mean_systolic = float(np.mean(systolic_values))
mean_diastolic = float(np.mean(diastolic_values))
mean_arterial_pressure = mean_diastolic + (mean_systolic - mean_diastolic) / 3.0
pulse_pressure = mean_systolic - mean_diastolic

heart_rate_bpm = None
if len(systolic_idx) >= 2:
    mean_interval_sec = float(np.mean(np.diff(systolic_idx))) / sampling_rate
    heart_rate_bpm = 60.0 / mean_interval_sec if mean_interval_sec > 0 else None

result = {
    "mean_systolic_pressure": mean_systolic,
    "mean_diastolic_pressure": mean_diastolic,
    "mean_arterial_pressure": mean_arterial_pressure,
    "pulse_pressure": pulse_pressure,
    "heart_rate_bpm": heart_rate_bpm,
    "n_systolic_peaks_detected": int(len(systolic_idx)),
    "n_diastolic_troughs_detected": int(len(diastolic_idx)),
}
with open(output_file, "w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(list(result.keys()))
    writer.writerow(list(result.values()))
print(_json.dumps(result))
"""

_THYROID_PK_SCRIPT = """
import numpy as np
from scipy.integrate import solve_ivp

parameters = _args["parameters"]
initial_conditions = _args["initial_conditions"]
time_span = tuple(_args["time_span"])
time_points = int(_args["time_points"])

compartments = list(initial_conditions.keys())
index_of = {name: i for i, name in enumerate(compartments)}
y0 = np.array([float(initial_conditions[name]) for name in compartments], dtype=float)

transfer_rates = parameters.get("transfer_rates", {})
elimination_rates = parameters.get("elimination_rates", {})
production_rates = parameters.get("production_rates", {})

transfers = []
for key, rate in transfer_rates.items():
    if "->" not in key:
        raise ValueError(f"transfer_rates key {key!r} must be formatted 'source->destination'.")
    src, dst = (part.strip() for part in key.split("->", 1))
    if src not in index_of or dst not in index_of:
        raise ValueError(f"transfer_rates key {key!r} references an unknown compartment.")
    transfers.append((index_of[src], index_of[dst], float(rate)))

elim = np.zeros(len(compartments))
for name, rate in elimination_rates.items():
    if name not in index_of:
        raise ValueError(f"elimination_rates references unknown compartment {name!r}.")
    elim[index_of[name]] = float(rate)

prod = np.zeros(len(compartments))
for name, rate in production_rates.items():
    if name not in index_of:
        raise ValueError(f"production_rates references unknown compartment {name!r}.")
    prod[index_of[name]] = float(rate)


def rhs(_t, y):
    dydt = prod - elim * y
    for src, dst, rate in transfers:
        flux = rate * y[src]
        dydt[src] -= flux
        dydt[dst] += flux
    return dydt


t_eval = np.linspace(time_span[0], time_span[1], time_points)
solution = solve_ivp(rhs, time_span, y0, t_eval=t_eval, method="LSODA")
if not solution.success:
    raise RuntimeError(f"ODE integration failed: {solution.message}")

result = {
    "compartments": compartments,
    "time": solution.t.tolist(),
    "concentrations": {name: solution.y[index_of[name]].tolist() for name in compartments},
    "final_concentrations": {name: float(solution.y[index_of[name]][-1]) for name in compartments},
}
print(_json.dumps(result))
"""

_AMYLOID_PLAQUES_SCRIPT = """
import os

import numpy as np
from skimage import color, filters, io, measure, morphology

image_path = "/workspace/" + _args["image_path"]
output_dir = "/workspace/" + _args["output_dir"]
threshold_method = _args["threshold_method"]
min_plaque_size = int(_args["min_plaque_size"])
manual_threshold = int(_args["manual_threshold"])
os.makedirs(output_dir, exist_ok=True)

img = io.imread(image_path)
if img.ndim == 3:
    gray_8bit = (color.rgb2gray(img[..., :3]) * 255).astype(np.uint8)
elif img.dtype != np.uint8:
    img_range = float(img.max()) - float(img.min()) or 1.0
    gray_8bit = (255.0 * (img.astype(float) - img.min()) / img_range).astype(np.uint8)
else:
    gray_8bit = img

if threshold_method == "manual":
    thresh = float(manual_threshold)
else:
    threshold_func = getattr(filters, "threshold_" + threshold_method, None)
    if threshold_func is None:
        raise ValueError(f"Unsupported threshold_method: {threshold_method!r}")
    thresh = float(threshold_func(gray_8bit))

mask = gray_8bit > thresh
mask = morphology.remove_small_objects(mask, min_size=min_plaque_size)

labeled = measure.label(mask)
regions = [r for r in measure.regionprops(labeled) if r.area >= min_plaque_size]

total_pixels = gray_8bit.shape[0] * gray_8bit.shape[1]
plaque_areas = [int(r.area) for r in regions]
total_plaque_area = int(sum(plaque_areas))

result = {
    "plaque_count": len(regions),
    "total_plaque_area_px": total_plaque_area,
    "percent_area_covered": float(100.0 * total_plaque_area / total_pixels) if total_pixels else 0.0,
    "mean_plaque_size_px": float(np.mean(plaque_areas)) if plaque_areas else 0.0,
    "median_plaque_size_px": float(np.median(plaque_areas)) if plaque_areas else 0.0,
    "threshold_method": threshold_method,
    "threshold_value_used": thresh,
    "method_disclaimer": (
        "General-purpose Otsu/manual threshold + connected-component blob quantification "
        "(scikit-image). Not clinically or publication validated."
    ),
}
print(_json.dumps(result))
"""

_DECODE_NEURAL_TRAJECTORIES_SCRIPT = """
import os

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

neural_data = np.array(_args["neural_data"], dtype=float)
behavioral_data = np.array(_args["behavioral_data"], dtype=float)
n_components = int(_args["n_components"])
output_dir = "/workspace/" + _args["output_dir"]
os.makedirs(output_dir, exist_ok=True)

n_components = max(1, min(n_components, neural_data.shape[0], neural_data.shape[1]))
pca = PCA(n_components=n_components)
neural_pcs = pca.fit_transform(neural_data)

model = LinearRegression()
model.fit(neural_pcs, behavioral_data)
predictions = model.predict(neural_pcs)
r_squared = float(r2_score(behavioral_data, predictions))

result = {
    "n_components_used": n_components,
    "explained_variance_ratio": [float(v) for v in pca.explained_variance_ratio_],
    "total_explained_variance": float(np.sum(pca.explained_variance_ratio_)),
    "r_squared": r_squared,
    "r_squared_is_in_sample": True,
    "coefficients": [float(c) for c in np.atleast_1d(model.coef_)],
}
print(_json.dumps(result))
"""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def analyze_aortic_diameter_and_geometry(arguments: dict, driver) -> dict:
    """Tier C: aortic lumen geometry (equivalent diameter, major/minor axis,
    area, perimeter, eccentricity, orientation) from a cardiovascular image
    (DICOM/JPG/PNG) via Otsu thresholding + largest-connected-component
    region properties (scikit-image), converting to mm when DICOM
    PixelSpacing is available. General-purpose method, NOT clinically or
    publication validated."""
    params = AorticDiameterArgs(**(arguments or {}))
    image_path = ensure_safe_relative_path(params.image_path)
    output_dir = ensure_safe_relative_path(params.output_dir)
    args = {"image_path": image_path, "output_dir": output_dir}
    return run_in_sandbox(driver, script_body=_AORTIC_DIAMETER_SCRIPT, args=args)


def analyze_thrombus_histology(arguments: dict, driver) -> dict:
    """Tier C: classifies H&E thrombus components (RBC-rich, fibrin/
    platelet-rich, leukocyte-rich) via Ruifrok & Johnston color
    deconvolution + Otsu thresholding (scikit-image). General-purpose
    method, NOT clinically or publication validated."""
    params = ThrombusHistologyArgs(**(arguments or {}))
    image_path = ensure_safe_relative_path(params.image_path)
    output_dir = ensure_safe_relative_path(params.output_dir)
    args = {"image_path": image_path, "output_dir": output_dir}
    return run_in_sandbox(driver, script_body=_THROMBUS_HISTOLOGY_SCRIPT, args=args)


def analyze_intracellular_calcium_with_rhod2(arguments: dict, driver) -> dict:
    """Tier C: background-subtracted Rhod-2 fluorescence F/F0 ratio between
    a control and sample image. General-purpose mean-intensity method, NOT
    clinically or publication validated."""
    params = Rhod2CalciumArgs(**(arguments or {}))
    args = {
        "background_image_path": ensure_safe_relative_path(params.background_image_path),
        "control_image_path": ensure_safe_relative_path(params.control_image_path),
        "sample_image_path": ensure_safe_relative_path(params.sample_image_path),
        "output_dir": ensure_safe_relative_path(params.output_dir),
    }
    return run_in_sandbox(driver, script_body=_RHOD2_CALCIUM_SCRIPT, args=args)


def quantify_corneal_nerve_fibers(arguments: dict, driver) -> dict:
    """Tier C: corneal nerve fiber density from an immunofluorescence image
    via threshold + skeletonization (scikit-image), reporting fiber length,
    density, branch-point count, and fiber-segment count.
    `threshold_method` dispatches to any `skimage.filters.threshold_*`
    function name (e.g. "otsu", "mean", "triangle", "yen"). General-purpose
    method, NOT clinically or publication validated."""
    params = CornealNerveFibersArgs(**(arguments or {}))
    args = {
        "image_path": ensure_safe_relative_path(params.image_path),
        "marker_type": params.marker_type,
        "output_dir": ensure_safe_relative_path(params.output_dir),
        "threshold_method": params.threshold_method,
    }
    return run_in_sandbox(driver, script_body=_CORNEAL_NERVE_FIBERS_SCRIPT, args=args)


def segment_and_quantify_cells_in_multiplexed_images(arguments: dict, driver) -> dict:
    """Tier C: nuclear-channel Otsu-threshold watershed segmentation of a
    multichannel tissue image, then per-marker positive-cell fraction from
    per-cell mean intensity thresholding (scikit-image/scipy.ndimage).
    `markers_list` must name every channel in the image, in channel order
    (including the nuclear channel itself). General-purpose method, NOT
    clinically or publication validated."""
    params = MultiplexedCellSegmentationArgs(**(arguments or {}))
    args = {
        "image_path": ensure_safe_relative_path(params.image_path),
        "markers_list": params.markers_list,
        "nuclear_channel_index": params.nuclear_channel_index,
        "output_dir": ensure_safe_relative_path(params.output_dir),
    }
    return run_in_sandbox(
        driver, script_body=_MULTIPLEXED_CELL_SEGMENTATION_SCRIPT, args=args
    )


def analyze_bone_microct_morphometry(arguments: dict, driver) -> dict:
    """Tier C: trabecular bone morphometry (BV/TV, Tb.Th, Tb.Sp, Tb.N) from
    a micro-CT NIfTI volume via threshold segmentation + marching-cubes
    surface area + the standard Parfitt plate-model stereology formulas.
    `bmd_proxy_mean_intensity` is an UNCALIBRATED mean voxel intensity, not
    a phantom-calibrated areal BMD. General-purpose method, NOT clinically
    or publication validated."""
    params = BoneMicroctMorphometryArgs(**(arguments or {}))
    args = {
        "input_file_path": ensure_safe_relative_path(params.input_file_path),
        "output_dir": ensure_safe_relative_path(params.output_dir),
        "threshold_value": params.threshold_value,
    }
    return run_in_sandbox(driver, script_body=_BONE_MICROCT_MORPHOMETRY_SCRIPT, args=args)


def reconstruct_3d_face_from_mri(arguments: dict, driver) -> dict:
    """Tier C: extracts a 3D surface mesh (Wavefront OBJ) from a NIfTI MRI
    volume at a fixed intensity isosurface via marching cubes
    (scikit-image), using nibabel for I/O. General-purpose method, NOT
    clinically or publication validated; not a diagnostic tool."""
    params = Reconstruct3dFaceArgs(**(arguments or {}))
    args = {
        "mri_file_path": ensure_safe_relative_path(params.mri_file_path),
        "output_dir": ensure_safe_relative_path(params.output_dir),
        "subject_id": params.subject_id,
        "threshold_value": params.threshold_value,
    }
    return run_in_sandbox(driver, script_body=_RECONSTRUCT_3D_FACE_SCRIPT, args=args)


def analyze_abr_waveform_p1_metrics(arguments: dict, driver) -> dict:
    """Tier A: P1 (wave I) latency/amplitude from an auditory brainstem
    response waveform -- baseline-corrects against the first 10% of
    samples, then finds the first prominent peak via
    `scipy.signal.find_peaks` (falling back to the global maximum if no
    peak clears the prominence threshold). Deterministic algorithm, no
    statistical model."""
    params = AbrWaveformArgs(**(arguments or {}))
    args = {"time_ms": params.time_ms, "amplitude_uv": params.amplitude_uv}
    return run_in_sandbox(driver, script_body=_ABR_WAVEFORM_SCRIPT, args=args)


def analyze_ciliary_beat_frequency(arguments: dict, driver) -> dict:
    """Tier C: ciliary beat frequency from a video via a grid of ROIs, mean
    per-frame intensity per ROI, and FFT dominant-frequency detection
    within `[min_freq, max_freq]` Hz (opencv + numpy). General-purpose
    method, NOT clinically or publication validated."""
    params = CiliaryBeatFrequencyArgs(**(arguments or {}))
    args = {
        "video_path": ensure_safe_relative_path(params.video_path),
        "roi_count": params.roi_count,
        "min_freq": params.min_freq,
        "max_freq": params.max_freq,
        "output_dir": ensure_safe_relative_path(params.output_dir),
    }
    return run_in_sandbox(driver, script_body=_CILIARY_BEAT_FREQUENCY_SCRIPT, args=args)


def analyze_protein_colocalization(arguments: dict, driver) -> dict:
    """Tier C: Pearson correlation coefficient + Manders M1/M2
    colocalization coefficients between two single-channel images
    (scipy.stats + scikit-image thresholding). `threshold_method`
    dispatches to any `skimage.filters.threshold_*` function name.
    General-purpose method, NOT clinically or publication validated."""
    params = ProteinColocalizationArgs(**(arguments or {}))
    args = {
        "channel1_path": ensure_safe_relative_path(params.channel1_path),
        "channel2_path": ensure_safe_relative_path(params.channel2_path),
        "output_dir": ensure_safe_relative_path(params.output_dir),
        "threshold_method": params.threshold_method,
    }
    return run_in_sandbox(driver, script_body=_PROTEIN_COLOCALIZATION_SCRIPT, args=args)


def perform_cosinor_analysis(arguments: dict, driver) -> dict:
    """Tier B: circadian-rhythm cosinor analysis (Nelson et al.
    formulation) -- fits `y = mesor + amplitude*cos(2*pi*t/period -
    acrophase)` via linear least squares on cos/sin regressors, a real
    closed-form method."""
    params = CosinorAnalysisArgs(**(arguments or {}))
    args = {
        "time_data": params.time_data,
        "physiological_data": params.physiological_data,
        "period": params.period,
    }
    return run_in_sandbox(driver, script_body=_COSINOR_ANALYSIS_SCRIPT, args=args)


def calculate_brain_adc_map(arguments: dict, driver) -> dict:
    """Tier B: per-voxel apparent diffusion coefficient (ADC) map from a 4D
    diffusion-weighted MRI NIfTI volume, via a real monoexponential fit
    (linear least squares on log(S) vs b-value per the S(b)=S0*exp(-b*ADC)
    model), saved as a new NIfTI file (nibabel)."""
    params = BrainAdcMapArgs(**(arguments or {}))
    args = {
        "dwi_file_path": ensure_safe_relative_path(params.dwi_file_path),
        "b_values": params.b_values,
        "output_path": ensure_safe_relative_path(params.output_path),
        "mask_file_path": _safe_optional_path(params.mask_file_path),
    }
    return run_in_sandbox(driver, script_body=_BRAIN_ADC_MAP_SCRIPT, args=args)


def analyze_endolysosomal_calcium_dynamics(arguments: dict, driver) -> dict:
    """Tier B: baseline/peak/decay kinetics from an endolysosomal calcium
    probe (e.g. GCaMP-based ELGA/ELGA1) luminescence time series --
    baseline from pre-treatment samples (or the first 10% if
    `treatment_time` is omitted), peak detection post-treatment, and a real
    `scipy.optimize.curve_fit` exponential decay fit for the post-peak
    segment."""
    params = EndolysosomalCalciumArgs(**(arguments or {}))
    args = {
        "time_points": params.time_points,
        "luminescence_values": params.luminescence_values,
        "treatment_time": params.treatment_time,
        "cell_type": params.cell_type,
        "treatment_name": params.treatment_name,
        "output_file": ensure_safe_relative_path(params.output_file),
    }
    return run_in_sandbox(driver, script_body=_ENDOLYSOSOMAL_CALCIUM_SCRIPT, args=args)


def analyze_fatty_acid_composition_by_gc(arguments: dict, driver) -> dict:
    """Tier A: fatty acid composition from a gas-chromatography peak-area
    table (a CSV with a `fatty_acid`/`compound`/`name` column and a
    `peak_area`/`area` column) -- deterministic peak-area normalization to
    percent composition, plus saturated/monounsaturated/polyunsaturated
    classification from the standard `Cxx:y` lipid nomenclature (y = number
    of double bonds). No statistical model."""
    params = FattyAcidGcArgs(**(arguments or {}))
    args = {
        "gc_data_file": ensure_safe_relative_path(params.gc_data_file),
        "tissue_type": params.tissue_type,
        "sample_id": params.sample_id,
        "output_directory": ensure_safe_relative_path(params.output_directory),
    }
    return run_in_sandbox(driver, script_body=_FATTY_ACID_GC_SCRIPT, args=args)


def analyze_hemodynamic_data(arguments: dict, driver) -> dict:
    """Tier B: derives systolic/diastolic/mean arterial pressure and heart
    rate from a blood-pressure waveform via `scipy.signal.find_peaks`
    peak/trough detection and the standard closed-form
    MAP = DBP + (SBP-DBP)/3 formula."""
    params = HemodynamicDataArgs(**(arguments or {}))
    args = {
        "pressure_data": params.pressure_data,
        "sampling_rate": params.sampling_rate,
        "output_file": ensure_safe_relative_path(params.output_file),
    }
    return run_in_sandbox(driver, script_body=_HEMODYNAMIC_DATA_SCRIPT, args=args)


def simulate_thyroid_hormone_pharmacokinetics(arguments: dict, driver) -> dict:
    """Tier B: ODE-based thyroid hormone pharmacokinetics across an
    arbitrary set of named compartments, via a real generic linear
    multi-compartment model (`transfer_rates`/`elimination_rates`/
    `production_rates` in `parameters`) integrated with
    `scipy.integrate.solve_ivp` (LSODA). See the module docstring for why
    this is a self-contained implementation of the same pattern rather than
    a cross-module import of a shared integrator."""
    params = ThyroidPkArgs(**(arguments or {}))
    args = {
        "parameters": params.parameters,
        "initial_conditions": params.initial_conditions,
        "time_span": list(params.time_span),
        "time_points": params.time_points,
    }
    return run_in_sandbox(driver, script_body=_THYROID_PK_SCRIPT, args=args)


def quantify_amyloid_beta_plaques(arguments: dict, driver) -> dict:
    """Tier C: amyloid-beta plaque count/area from a stained image via
    Otsu (or `manual_threshold`) thresholding + connected-component
    filtering by `min_plaque_size` (scikit-image). General-purpose method,
    NOT clinically or publication validated."""
    params = AmyloidPlaquesArgs(**(arguments or {}))
    args = {
        "image_path": ensure_safe_relative_path(params.image_path),
        "output_dir": ensure_safe_relative_path(params.output_dir),
        "threshold_method": params.threshold_method,
        "min_plaque_size": params.min_plaque_size,
        "manual_threshold": params.manual_threshold,
    }
    return run_in_sandbox(driver, script_body=_AMYLOID_PLAQUES_SCRIPT, args=args)


def decode_behavior_from_neural_trajectories(arguments: dict, driver) -> dict:
    """Tier B: decodes a behavioral variable from neural population
    trajectories via real PCA dimensionality reduction (sklearn) followed
    by linear regression, reporting explained variance and an in-sample R^2
    (`r_squared_is_in_sample: true` -- no held-out cross-validation is
    performed, so this is not reported as a generalization estimate)."""
    params = DecodeNeuralTrajectoriesArgs(**(arguments or {}))
    args = {
        "neural_data": params.neural_data,
        "behavioral_data": params.behavioral_data,
        "n_components": params.n_components,
        "output_dir": ensure_safe_relative_path(params.output_dir),
    }
    return run_in_sandbox(
        driver, script_body=_DECODE_NEURAL_TRAJECTORIES_SCRIPT, args=args
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_TOOL_HANDLERS = {
    "analyze_aortic_diameter_and_geometry": analyze_aortic_diameter_and_geometry,
    "analyze_thrombus_histology": analyze_thrombus_histology,
    "analyze_intracellular_calcium_with_rhod2": analyze_intracellular_calcium_with_rhod2,
    "quantify_corneal_nerve_fibers": quantify_corneal_nerve_fibers,
    "segment_and_quantify_cells_in_multiplexed_images": (
        segment_and_quantify_cells_in_multiplexed_images
    ),
    "analyze_bone_microct_morphometry": analyze_bone_microct_morphometry,
    "reconstruct_3d_face_from_mri": reconstruct_3d_face_from_mri,
    "analyze_abr_waveform_p1_metrics": analyze_abr_waveform_p1_metrics,
    "analyze_ciliary_beat_frequency": analyze_ciliary_beat_frequency,
    "analyze_protein_colocalization": analyze_protein_colocalization,
    "perform_cosinor_analysis": perform_cosinor_analysis,
    "calculate_brain_adc_map": calculate_brain_adc_map,
    "analyze_endolysosomal_calcium_dynamics": analyze_endolysosomal_calcium_dynamics,
    "analyze_fatty_acid_composition_by_gc": analyze_fatty_acid_composition_by_gc,
    "analyze_hemodynamic_data": analyze_hemodynamic_data,
    "simulate_thyroid_hormone_pharmacokinetics": simulate_thyroid_hormone_pharmacokinetics,
    "quantify_amyloid_beta_plaques": quantify_amyloid_beta_plaques,
    "decode_behavior_from_neural_trajectories": decode_behavior_from_neural_trajectories,
}


def register_physiology_imaging_tools(registry, driver) -> List[str]:
    """Registers every "Categoria: Fisiologia / cardio / neuro / imaging"
    tool into `registry`, each bound to the shared sandbox `driver`. Returns
    the registered tool names."""
    for name, handler in _TOOL_HANDLERS.items():
        registry.register_server(name, functools.partial(handler, driver=driver))
    return list(_TOOL_HANDLERS.keys())
