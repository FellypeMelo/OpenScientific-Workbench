"""Cell biology & imaging action tools (Fase 5).

Implements every tool listed under "## Categoria: Cell biology & imaging" in
``backend/docs/tools/action_tool_catalog.md``. That heading tiers the whole
category as **Tier C** by default (real scikit-image/opencv/trackpy/flowio
pipelines -- general-purpose image/flow-cytometry processing, NOT clinically
or publication validated), with two individually-tiered exceptions called out
in the catalog itself:

- ``estimate_cell_cycle_phase_durations`` -- **Tier B** (a real
  ``scipy.optimize.curve_fit`` fit of a 3-compartment cell-cycle ODE model to
  pulse-labeling time-course data).
- ``predict_protein_disorder_regions`` -- **Tier A** (a real, documented,
  cited algorithm -- see that function's docstring for why FoldIndex was
  implemented instead of IUPred2A specifically).

There are no Tier D tools in this category (nothing here needs a proprietary
pretrained checkpoint or a GPU cluster), so nothing is added to
``backend/docs/tools/UNSUPPORTED.md``.

Every handler follows the pattern mandated by ``_sandbox_tool_base.py``:
validate arguments with a Pydantic model (raising ``ValidationError``, a
``ValueError`` subclass, on bad input -- BEFORE any sandbox call happens),
run any file-path argument through
``domain/services/path_guard.py::ensure_safe_relative_path``, then hand a
short, hand-written ``script_body`` (real biopython/scipy/scikit-image/opencv/
trackpy/flowio calls, never a template that stringifies arbitrary code) to
``run_in_sandbox`` for execution inside the bwrap jail. Arguments always flow
into the sandboxed script as the parsed ``_args`` dict (written to a JSON file
and read back by ``run_in_sandbox`` itself) -- never spliced into the script
source as a literal, and never used to build a shell command string.

TESTING BOUNDARY (see ``_sandbox_tool_base.py``'s module docstring for the
full rationale): this repo's own pytest venv has no scikit-image/opencv/
trackpy/flowio -- those only exist in the sandbox toolkit's conda env
(``backend/sandbox/environment.yml``). ``tests/unit/test_cell_imaging.py``
therefore verifies argument validation and script/args wiring via
``FakeSandboxDriver``, never live numeric correctness of a ``script_body``.

Dependency note: reading TIFF stacks (calcium imaging, time-lapse migration
sequences) needs ``tifffile``, which was not yet declared in
``backend/sandbox/environment.yml``. It has been added there (conda-forge,
real widely-used package) as part of this change -- the sandbox image has not
been rebuilt in this session, so the exact solve is not independently
re-verified here, matching this repo's existing convention for
``environment.yml`` entries (see that file's own top-of-file caveat).
"""
from __future__ import annotations

import textwrap
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from src.domain.services.path_guard import ensure_safe_relative_path
from src.infrastructure.tools._sandbox_tool_base import run_in_sandbox

TIER_C_DISCLAIMER = (
    "General-purpose scikit-image/opencv/trackpy/flowio pipeline -- NOT "
    "clinically or publication validated. Treat results as exploratory, not "
    "diagnostic."
)

_VALID_THRESHOLD_METHODS = {"otsu", "mean"}


# ---------------------------------------------------------------------------
# Shared, hand-written script fragments. These are trusted code composed at
# the Python-string level -- never string-interpolated with `_args` values
# (which stay data, round-tripped through the JSON file `run_in_sandbox`
# writes/reads for the sandboxed process).
# ---------------------------------------------------------------------------

_IMAGE_STACK_LOADER = textwrap.dedent(
    """
    import os
    import glob
    import numpy as np
    import tifffile

    def _load_stack(path):
        # Loads a (T, H, W[, C]) stack from either a multi-page TIFF file or
        # a directory of single-frame TIFF images (sorted by filename).
        if os.path.isdir(path):
            files = sorted(glob.glob(os.path.join(path, "*")))
            frames = [tifffile.imread(f) for f in files]
            if not frames:
                raise ValueError("No image frames found in directory: " + path)
            return np.stack(frames, axis=0)
        return np.asarray(tifffile.imread(path))
    """
)

_PARTICLE_DETECTION = textwrap.dedent(
    """
    from skimage.filters import threshold_otsu
    from skimage.measure import label, regionprops
    import pandas as pd

    def _detect_particles(stack):
        rows = []
        for t, frame in enumerate(stack):
            frame = np.asarray(frame, dtype=float)
            if frame.ndim == 3:
                frame = frame.mean(axis=-1)
            thresh = threshold_otsu(frame)
            mask = frame > thresh
            labeled = label(mask)
            for region in regionprops(labeled):
                if region.area < 4:
                    continue
                y, x = region.centroid
                rows.append({"frame": t, "x": x, "y": y, "area": region.area})
        return pd.DataFrame(rows)
    """
)


# ---------------------------------------------------------------------------
# Argument models
# ---------------------------------------------------------------------------


class AnalyzeCellMigrationMetricsArgs(BaseModel):
    image_sequence_path: str
    pixel_size_um: float = Field(default=1.0, gt=0)
    time_interval_min: float = Field(default=1.0, gt=0)
    min_track_length: int = Field(default=10, ge=1)
    output_dir: str = "./output"


class AnalyzeCalciumImagingDataArgs(BaseModel):
    image_stack_path: str
    output_dir: str = "./output"


class AnalyzeMyofiberMorphologyArgs(BaseModel):
    image_path: str
    nuclei_channel: int = Field(default=2, ge=0)
    myofiber_channel: int = Field(default=1, ge=0)
    threshold_method: str = "otsu"
    output_dir: str = "./output"

    @field_validator("threshold_method")
    @classmethod
    def _validate_method(cls, v: str) -> str:
        if v not in _VALID_THRESHOLD_METHODS:
            raise ValueError(f"threshold_method must be one of {sorted(_VALID_THRESHOLD_METHODS)}")
        return v


class QuantifyCellCyclePhasesArgs(BaseModel):
    image_paths: List[str]
    output_dir: str = "./results"

    @field_validator("image_paths")
    @classmethod
    def _validate_paths(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("image_paths must contain at least one path")
        return v


class QuantifyAndClusterCellMotilityArgs(BaseModel):
    image_sequence_path: str
    output_dir: str = "./results"
    num_clusters: int = Field(default=3, ge=1)


class AnalyzeMitochondrialMorphologyArgs(BaseModel):
    morphology_image_path: str
    potential_image_path: str
    output_dir: str = "./output"


class AnalyzeCellMorphologyCytoskeletonArgs(BaseModel):
    image_path: str
    output_dir: str = "./results"
    threshold_method: str = "otsu"

    @field_validator("threshold_method")
    @classmethod
    def _validate_method(cls, v: str) -> str:
        if v not in _VALID_THRESHOLD_METHODS:
            raise ValueError(f"threshold_method must be one of {sorted(_VALID_THRESHOLD_METHODS)}")
        return v


class AnalyzeTissueDeformationFlowArgs(BaseModel):
    image_sequence: List[Any]
    output_dir: str = "results"
    pixel_scale: float = Field(default=1.0, gt=0)

    @field_validator("image_sequence")
    @classmethod
    def _validate_sequence(cls, v: List[Any]) -> List[Any]:
        if len(v) < 2:
            raise ValueError("image_sequence must contain at least 2 frames")
        return v


class AnalyzeCellSenescenceApoptosisArgs(BaseModel):
    fcs_file_path: str


class PerformFacsCellSortingArgs(BaseModel):
    cell_suspension_data: str
    fluorescence_parameter: str
    threshold_min: Optional[float] = None
    threshold_max: Optional[float] = None
    output_file: str = "sorted_cells.csv"

    @field_validator("fluorescence_parameter")
    @classmethod
    def _validate_param(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("fluorescence_parameter must not be empty")
        return v


class AnalyzeFlowCytometryImmunophenotypingArgs(BaseModel):
    fcs_file_path: str
    gating_strategy: Dict[str, Dict[str, Any]]
    compensation_matrix: Optional[List[List[float]]] = None
    output_dir: str = "./results"

    @field_validator("gating_strategy")
    @classmethod
    def _validate_gates(cls, v: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        if not v:
            raise ValueError("gating_strategy must contain at least one gate")
        for gate_name, gate in v.items():
            if "channel" not in gate:
                raise ValueError(f"gate '{gate_name}' is missing the required 'channel' key")
        return v

    @field_validator("compensation_matrix")
    @classmethod
    def _validate_square(
        cls, v: Optional[List[List[float]]]
    ) -> Optional[List[List[float]]]:
        if v is not None:
            n = len(v)
            if n == 0 or any(len(row) != n for row in v):
                raise ValueError("compensation_matrix must be a non-empty square matrix")
        return v


class AnalyzeCfseCellProliferationArgs(BaseModel):
    fcs_file_path: str
    cfse_channel: str = "FL1-A"
    lymphocyte_gate: Optional[Tuple[float, float]] = None


class EstimateCellCyclePhaseDurationsArgs(BaseModel):
    flow_cytometry_data: Dict[str, Any]
    initial_estimates: Dict[str, Any]

    @field_validator("flow_cytometry_data")
    @classmethod
    def _validate_data(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if "time_points" not in v:
            raise ValueError("flow_cytometry_data must include 'time_points'")
        if "fraction_S" not in v and "labeled_fraction" not in v:
            raise ValueError(
                "flow_cytometry_data must include either 'fraction_S' or 'labeled_fraction'"
            )
        return v


class PredictProteinDisorderRegionsArgs(BaseModel):
    protein_sequence: str
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    output_file: str = "disorder_prediction_results.csv"

    @field_validator("protein_sequence")
    @classmethod
    def _validate_sequence(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("protein_sequence must not be empty")
        valid = set("ACDEFGHIKLMNPQRSTVWYXBZJUO")
        if not set(cleaned).issubset(valid):
            bad = sorted(set(cleaned) - valid)
            raise ValueError(f"protein_sequence contains invalid characters: {bad}")
        return cleaned


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def analyze_cell_migration_metrics(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Segments each frame of a time-lapse image sequence via Otsu thresholding,
    links detections into trajectories with ``trackpy``, and computes
    per-track migration metrics (path length, net displacement, mean speed,
    persistence) scaled by ``pixel_size_um``/``time_interval_min``.
    """
    args = AnalyzeCellMigrationMetricsArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["image_sequence_path"] = ensure_safe_relative_path(validated["image_sequence_path"])
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = (
        _IMAGE_STACK_LOADER
        + _PARTICLE_DETECTION
        + textwrap.dedent(
            """
            import os

            stack = _load_stack(_args["image_sequence_path"])
            if stack.ndim == 2:
                stack = stack[None, ...]

            detections = _detect_particles(stack)
            os.makedirs(_args["output_dir"], exist_ok=True)

            if detections.empty:
                result = {
                    "n_tracks": 0,
                    "mean_speed_um_per_min": None,
                    "mean_persistence": None,
                    "tracks": [],
                }
            else:
                import trackpy as tp

                search_range = max(5.0, float(np.sqrt(detections["area"].median())) * 3)
                linked = tp.link(detections, search_range=search_range, memory=1)
                linked = tp.filter_stubs(linked, threshold=_args["min_track_length"])

                pixel_size = _args["pixel_size_um"]
                dt_min = _args["time_interval_min"]
                tracks_summary = []
                for pid, g in linked.sort_values("frame").groupby("particle"):
                    xy = g[["x", "y"]].to_numpy() * pixel_size
                    steps = np.diff(xy, axis=0)
                    step_lengths = np.linalg.norm(steps, axis=1) if len(steps) else np.array([])
                    path_length = float(step_lengths.sum())
                    net_displacement = float(np.linalg.norm(xy[-1] - xy[0])) if len(xy) > 1 else 0.0
                    duration_min = (float(g["frame"].max()) - float(g["frame"].min())) * dt_min
                    mean_speed = path_length / duration_min if duration_min > 0 else 0.0
                    persistence = net_displacement / path_length if path_length > 0 else 0.0
                    tracks_summary.append({
                        "particle_id": int(pid),
                        "n_points": int(len(g)),
                        "path_length_um": path_length,
                        "net_displacement_um": net_displacement,
                        "mean_speed_um_per_min": mean_speed,
                        "persistence": persistence,
                    })

                tracks_df = pd.DataFrame(tracks_summary)
                tracks_csv = os.path.join(_args["output_dir"], "migration_tracks.csv")
                tracks_df.to_csv(tracks_csv, index=False)
                result = {
                    "n_tracks": int(len(tracks_summary)),
                    "mean_speed_um_per_min": (
                        float(tracks_df["mean_speed_um_per_min"].mean()) if len(tracks_df) else None
                    ),
                    "mean_persistence": (
                        float(tracks_df["persistence"].mean()) if len(tracks_df) else None
                    ),
                    "tracks_csv": tracks_csv,
                }

            result["method"] = (
                "Otsu threshold segmentation + trackpy linking (general-purpose, not "
                "clinically validated)."
            )
            print(_json.dumps(result))
            """
        )
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def analyze_calcium_imaging_data(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Segments a calcium-imaging TIFF stack by std-projection Otsu thresholding,
    extracts per-ROI mean-intensity dF/F traces, detects activity events by
    threshold crossing, fits an exponential decay to each event
    (``scipy.optimize.curve_fit``), and reports per-cell event rate/SNR. No
    frame interval is supplied by this tool's signature, so event rate is
    reported per-frame (not per-minute) to avoid fabricating a time unit.
    """
    args = AnalyzeCalciumImagingDataArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["image_stack_path"] = ensure_safe_relative_path(validated["image_stack_path"])
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = (
        _IMAGE_STACK_LOADER
        + textwrap.dedent(
            """
            import os
            from skimage.filters import threshold_otsu
            from skimage.measure import label, regionprops
            from scipy.optimize import curve_fit

            stack = _load_stack(_args["image_stack_path"])
            if stack.ndim == 2:
                stack = stack[None, ...]
            T = stack.shape[0]

            std_proj = stack.astype(float).std(axis=0)
            thresh = threshold_otsu(std_proj)
            mask = std_proj > thresh
            labeled = label(mask)

            def _exp_decay(t, a, tau, c):
                return a * np.exp(-t / tau) + c

            cells = []
            for region in regionprops(labeled):
                if region.area < 4:
                    continue
                coords = region.coords
                trace = stack[:, coords[:, 0], coords[:, 1]].astype(float).mean(axis=1)
                f0 = float(np.percentile(trace, 10))
                f0 = f0 if abs(f0) > 1e-6 else 1e-6
                dff = (trace - f0) / f0
                baseline_window = dff[: max(5, T // 10)]
                noise_std = float(np.std(baseline_window)) or float(np.std(dff)) or 1e-6
                event_threshold = 3 * noise_std

                peaks = []
                i = 0
                while i < T:
                    if dff[i] > event_threshold:
                        peaks.append(i)
                        i += 1
                        while i < T and dff[i] > event_threshold * 0.5:
                            i += 1
                    else:
                        i += 1

                decay_times = []
                for p in peaks:
                    tail = dff[p: min(T, p + 20)]
                    if len(tail) < 4:
                        continue
                    try:
                        popt, _ = curve_fit(
                            _exp_decay, np.arange(len(tail)), tail,
                            p0=[max(float(tail[0]), 1e-3), 3.0, 0.0], maxfev=2000,
                        )
                        if popt[1] > 0:
                            decay_times.append(float(popt[1]))
                    except Exception:
                        continue

                peak_amp = float(np.max(dff)) if len(dff) else 0.0
                snr = peak_amp / noise_std if noise_std > 0 else 0.0
                cells.append({
                    "cell_id": int(region.label),
                    "area_px": int(region.area),
                    "n_events": len(peaks),
                    "event_rate_per_frame": (len(peaks) / T) if T else 0.0,
                    "mean_decay_time_frames": float(np.mean(decay_times)) if decay_times else None,
                    "snr": snr,
                })

            os.makedirs(_args["output_dir"], exist_ok=True)
            result = {
                "n_frames": int(T),
                "n_cells": len(cells),
                "cells": cells,
                "method": (
                    "Std-projection Otsu segmentation + 3-sigma event threshold detection + "
                    "exponential decay curve_fit (general-purpose, not clinically validated)."
                ),
            }
            print(_json.dumps(result))
            """
        )
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def analyze_myofiber_morphology(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Segments the myofiber channel of a multi-channel image via watershed
    (distance-transform local maxima as seeds), computes per-fiber minimum
    Feret diameter (the standard myofiber morphometry parameter) and central
    nucleation percentage (fraction of fibers whose nuclei-channel signal is
    centrally rather than peripherally located -- a classic muscle-pathology
    marker).
    """
    args = AnalyzeMyofiberMorphologyArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["image_path"] = ensure_safe_relative_path(validated["image_path"])
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = textwrap.dedent(
        """
        import os
        import numpy as np
        import tifffile
        from scipy import ndimage as ndi
        from skimage.filters import threshold_otsu
        from skimage.feature import peak_local_max
        from skimage.measure import label, regionprops
        from skimage.segmentation import watershed

        def _channel(img, idx):
            if img.ndim == 2:
                return img.astype(float)
            if img.shape[0] <= 8 and img.shape[0] < img.shape[-1]:
                return img[idx].astype(float)
            return img[..., idx].astype(float)

        def _axis_len(region, which):
            return getattr(region, "axis_" + which + "_length", None) or getattr(
                region, which + "_axis_length", 1.0
            )

        img = np.asarray(tifffile.imread(_args["image_path"]))
        myo = _channel(img, _args["myofiber_channel"])
        nuc = _channel(img, _args["nuclei_channel"])

        if _args["threshold_method"] == "otsu":
            t = threshold_otsu(myo)
        else:
            t = float(np.mean(myo) + np.std(myo))
        mask = myo > t

        distance = ndi.distance_transform_edt(mask)
        coords = peak_local_max(distance, labels=mask, min_distance=5)
        peak_mask = np.zeros_like(distance, dtype=bool)
        if len(coords):
            peak_mask[tuple(coords.T)] = True
        markers = label(peak_mask)
        labels_ws = watershed(-distance, markers, mask=mask)

        nuc_t = threshold_otsu(nuc)
        nuc_mask = nuc > nuc_t
        nuc_labeled = label(nuc_mask)
        nuc_centroids = np.array([r.centroid for r in regionprops(nuc_labeled)])

        fibers = []
        central_count = 0
        for region in regionprops(labels_ws):
            if region.area < 20:
                continue
            min_feret = float(min(_axis_len(region, "minor"), _axis_len(region, "major")))
            cy, cx = region.centroid
            n_in_fiber = 0
            is_central = False
            if len(nuc_centroids):
                yy = nuc_centroids[:, 0].astype(int).clip(0, labels_ws.shape[0] - 1)
                xx = nuc_centroids[:, 1].astype(int).clip(0, labels_ws.shape[1] - 1)
                in_fiber = labels_ws[yy, xx] == region.label
                n_in_fiber = int(in_fiber.sum())
                if n_in_fiber:
                    dists = np.linalg.norm(nuc_centroids[in_fiber] - np.array([cy, cx]), axis=1)
                    radius = float(np.sqrt(region.area / np.pi))
                    is_central = bool((dists < radius * 0.5).any())
            fibers.append({
                "fiber_id": int(region.label),
                "area_px": float(region.area),
                "min_feret_diameter_px": min_feret,
                "n_nuclei": n_in_fiber,
                "centrally_nucleated": is_central,
            })
            if is_central:
                central_count += 1

        os.makedirs(_args["output_dir"], exist_ok=True)
        result = {
            "n_fibers": len(fibers),
            "mean_min_feret_diameter_px": (
                float(np.mean([f["min_feret_diameter_px"] for f in fibers])) if fibers else None
            ),
            "pct_centrally_nucleated": (central_count / len(fibers) * 100) if fibers else 0.0,
            "fibers": fibers,
            "method": (
                "Otsu/mean+std threshold + watershed segmentation; minimum Feret diameter and "
                "central nucleation fraction are standard myofiber morphometry parameters "
                "(general-purpose, not clinically validated)."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def quantify_cell_cycle_phases_from_microscopy(
    arguments: Dict[str, Any], driver
) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Classifies Calcofluor-white-stained cells by budding index (a classic
    yeast morphological cell-cycle proxy): unbudded cells are scored G1,
    small-budded (bud area < 50% of the mother) S, and large-budded (bud area
    >= 50%) G2/M. Mother/bud pairs are separated with a distance-transform
    watershed split of each connected blob.
    """
    args = QuantifyCellCyclePhasesArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["image_paths"] = [ensure_safe_relative_path(p) for p in validated["image_paths"]]
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = textwrap.dedent(
        """
        import os
        import numpy as np
        import tifffile
        from scipy import ndimage as ndi
        from skimage.filters import threshold_otsu
        from skimage.feature import peak_local_max
        from skimage.measure import label, regionprops
        from skimage.segmentation import watershed

        phase_counts = {"unbudded_G1": 0, "small_budded_S": 0, "large_budded_G2M": 0}
        per_image = []

        for path in _args["image_paths"]:
            img = np.asarray(tifffile.imread(path), dtype=float)
            if img.ndim == 3:
                img = img.mean(axis=-1)
            t = threshold_otsu(img)
            mask = img > t
            distance = ndi.distance_transform_edt(mask)
            coords = peak_local_max(distance, labels=mask, min_distance=4)
            peak_mask = np.zeros_like(distance, dtype=bool)
            if len(coords):
                peak_mask[tuple(coords.T)] = True
            markers = label(peak_mask)
            ws = watershed(-distance, markers, mask=mask)
            cell_mask_labels = label(mask)

            n_cells_this_image = 0
            for cell_region in regionprops(cell_mask_labels):
                if cell_region.area < 15:
                    continue
                n_cells_this_image += 1
                sub = ws[cell_region.slice][cell_region.image]
                sub_labels = np.unique(sub)
                sub_labels = sub_labels[sub_labels != 0]
                if len(sub_labels) <= 1:
                    phase_counts["unbudded_G1"] += 1
                    continue
                sub_areas = sorted((int((ws == lbl).sum()) for lbl in sub_labels), reverse=True)
                ratio = sub_areas[1] / sub_areas[0] if sub_areas[0] else 0.0
                if ratio < 0.5:
                    phase_counts["small_budded_S"] += 1
                else:
                    phase_counts["large_budded_G2M"] += 1

            per_image.append({"image_path": path, "n_cells": n_cells_this_image})

        total = sum(phase_counts.values())
        pct = {k: (v / total * 100 if total else 0.0) for k, v in phase_counts.items()}

        os.makedirs(_args["output_dir"], exist_ok=True)
        result = {
            "total_cells": total,
            "phase_counts": phase_counts,
            "phase_percentages": pct,
            "per_image": per_image,
            "method": (
                "Calcofluor-white budding-index classification via watershed-split area ratio "
                "(unbudded=G1, small-bud<50% mother area=S, large-bud>=50%=G2/M); a general-purpose "
                "morphological proxy, not a validated flow-cytometry-grade cell-cycle assay."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def quantify_and_cluster_cell_motility(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Reuses the same Otsu + trackpy detection/linking pipeline as
    ``analyze_cell_migration_metrics``, extracts per-track motility features
    (mean speed, straightness, turning-angle variance, MSD-derived diffusion
    coefficient), and clusters tracks into ``num_clusters`` groups with
    ``sklearn.cluster.KMeans``.
    """
    args = QuantifyAndClusterCellMotilityArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["image_sequence_path"] = ensure_safe_relative_path(validated["image_sequence_path"])
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = (
        _IMAGE_STACK_LOADER
        + _PARTICLE_DETECTION
        + textwrap.dedent(
            """
            import os
            import trackpy as tp
            from sklearn.cluster import KMeans

            stack = _load_stack(_args["image_sequence_path"])
            if stack.ndim == 2:
                stack = stack[None, ...]

            detections = _detect_particles(stack)
            os.makedirs(_args["output_dir"], exist_ok=True)

            if detections.empty or len(detections) < 2:
                result = {"n_tracks": 0, "n_clusters": 0, "tracks": []}
            else:
                search_range = max(5.0, float(np.sqrt(detections["area"].median())) * 3)
                linked = tp.link(detections, search_range=search_range, memory=1)
                linked = tp.filter_stubs(linked, threshold=5)

                features, ids = [], []
                for pid, g in linked.sort_values("frame").groupby("particle"):
                    xy = g[["x", "y"]].to_numpy()
                    if len(xy) < 3:
                        continue
                    steps = np.diff(xy, axis=0)
                    step_lengths = np.linalg.norm(steps, axis=1)
                    path_length = float(step_lengths.sum())
                    net_displacement = float(np.linalg.norm(xy[-1] - xy[0]))
                    mean_speed = float(step_lengths.mean())
                    straightness = net_displacement / path_length if path_length > 0 else 0.0
                    angles = np.arctan2(steps[:, 1], steps[:, 0])
                    turning = np.diff(angles)
                    turning = (turning + np.pi) % (2 * np.pi) - np.pi
                    turning_var = float(np.var(turning)) if len(turning) else 0.0
                    lags = list(range(1, min(6, len(xy))))
                    msd = []
                    for lag in lags:
                        disp = xy[lag:] - xy[:-lag]
                        msd.append(float(np.mean(np.sum(disp ** 2, axis=1))))
                    diff_coeff = float(np.polyfit(lags, msd, 1)[0] / 4.0) if len(msd) >= 2 else 0.0
                    features.append([mean_speed, straightness, turning_var, diff_coeff])
                    ids.append(int(pid))

                n_clusters = min(_args["num_clusters"], max(1, len(features)))
                X = np.array(features) if features else np.zeros((0, 4))
                if len(X):
                    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=0)
                    assignments = km.fit_predict(X)
                    centers = km.cluster_centers_.tolist()
                else:
                    assignments = []
                    centers = []

                tracks_out = [
                    {
                        "particle_id": pid,
                        "mean_speed": f[0],
                        "straightness": f[1],
                        "turning_angle_variance": f[2],
                        "diffusion_coefficient": f[3],
                        "cluster": int(c),
                    }
                    for pid, f, c in zip(ids, features, assignments)
                ]
                result = {
                    "n_tracks": len(tracks_out),
                    "n_clusters": n_clusters,
                    "cluster_centers": centers,
                    "tracks": tracks_out,
                }

            result["method"] = (
                "Otsu segmentation + trackpy linking; features = mean speed, straightness, "
                "turning-angle variance, MSD-derived diffusion coefficient; sklearn KMeans "
                "clustering (general-purpose, not clinically validated)."
            )
            print(_json.dumps(result))
            """
        )
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def analyze_mitochondrial_morphology_and_potential(
    arguments: Dict[str, Any], driver
) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Segments the morphology-channel image (e.g. MTS-GFP) by Otsu threshold,
    computes per-mitochondrion shape metrics (area, aspect ratio, skeleton
    length via ``skimage.morphology.skeletonize``), and reports a normalized
    membrane-potential index (mean potential-channel intensity divided by mean
    morphology-channel intensity within the segmented mask, a TMRE-style
    normalized ratio).
    """
    args = AnalyzeMitochondrialMorphologyArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["morphology_image_path"] = ensure_safe_relative_path(
        validated["morphology_image_path"]
    )
    validated["potential_image_path"] = ensure_safe_relative_path(
        validated["potential_image_path"]
    )
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = textwrap.dedent(
        """
        import os
        import numpy as np
        import tifffile
        from skimage.filters import threshold_otsu
        from skimage.measure import label, regionprops
        from skimage.morphology import skeletonize

        def _axis_len(region, which):
            return getattr(region, "axis_" + which + "_length", None) or getattr(
                region, which + "_axis_length", 1.0
            )

        morph = np.asarray(tifffile.imread(_args["morphology_image_path"]), dtype=float)
        if morph.ndim == 3:
            morph = morph.mean(axis=-1)
        potential = np.asarray(tifffile.imread(_args["potential_image_path"]), dtype=float)
        if potential.ndim == 3:
            potential = potential.mean(axis=-1)

        t = threshold_otsu(morph)
        mask = morph > t
        labeled = label(mask)
        skeleton = skeletonize(mask)

        mito = []
        for region in regionprops(labeled, intensity_image=potential):
            if region.area < 3:
                continue
            major = _axis_len(region, "major") or 1.0
            minor = _axis_len(region, "minor") or 1.0
            aspect_ratio = major / minor if minor > 0 else 0.0
            skel_len = int(skeleton[region.slice][region.image].sum())
            mito.append({
                "mito_id": int(region.label),
                "area_px": float(region.area),
                "aspect_ratio": float(aspect_ratio),
                "skeleton_length_px": skel_len,
                "mean_potential_intensity": float(region.mean_intensity),
            })

        os.makedirs(_args["output_dir"], exist_ok=True)
        n = len(mito)
        mean_morph = float(morph[mask].mean()) if mask.any() else 0.0
        mean_potential = float(potential[mask].mean()) if mask.any() else 0.0
        potential_index = mean_potential / mean_morph if mean_morph > 0 else 0.0

        result = {
            "n_mitochondria": n,
            "mean_area_px": float(np.mean([m["area_px"] for m in mito])) if n else None,
            "mean_aspect_ratio": float(np.mean([m["aspect_ratio"] for m in mito])) if n else None,
            "total_skeleton_length_px": int(skeleton.sum()),
            "membrane_potential_index": potential_index,
            "mitochondria": mito,
            "method": (
                "Otsu segmentation of the morphology channel + skeletonization for network metrics; "
                "membrane potential index = mean(potential channel)/mean(morphology channel) within "
                "the mask, a normalized TMRE-style intensity ratio (general-purpose, not clinically "
                "validated)."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def analyze_cell_morphology_and_cytoskeleton(
    arguments: Dict[str, Any], driver
) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Segments cells by threshold, computes standard shape metrics (area,
    perimeter, eccentricity, solidity, circularity) via
    ``skimage.measure.regionprops``, and quantifies cytoskeletal fiber
    alignment using structure-tensor eigenvalue coherence (an
    OrientationJ-style alignment measure).
    """
    args = AnalyzeCellMorphologyCytoskeletonArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["image_path"] = ensure_safe_relative_path(validated["image_path"])
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = textwrap.dedent(
        """
        import os
        import numpy as np
        import tifffile
        from skimage.filters import threshold_otsu
        from skimage.measure import label, regionprops
        from skimage.feature import structure_tensor, structure_tensor_eigenvalues

        img = np.asarray(tifffile.imread(_args["image_path"]), dtype=float)
        if img.ndim == 3:
            img = img.mean(axis=-1)

        if _args["threshold_method"] == "otsu":
            t = threshold_otsu(img)
        else:
            t = float(np.mean(img) + np.std(img))
        mask = img > t
        labeled = label(mask)

        Axx, Axy, Ayy = structure_tensor(img, sigma=1.5)
        eigvals = structure_tensor_eigenvalues([Axx, Axy, Ayy])
        denom = eigvals[0] + eigvals[1]
        coherence_map = np.zeros_like(img)
        valid = denom > 1e-9
        coherence_map[valid] = (eigvals[0][valid] - eigvals[1][valid]) / denom[valid]
        orientation_map = 0.5 * np.arctan2(2 * Axy, (Axx - Ayy))

        cells = []
        for region in regionprops(labeled):
            if region.area < 10:
                continue
            coh = coherence_map[region.slice][region.image]
            orient = orientation_map[region.slice][region.image]
            circularity = (
                (4 * np.pi * region.area / (region.perimeter ** 2)) if region.perimeter > 0 else 0.0
            )
            cells.append({
                "cell_id": int(region.label),
                "area_px": float(region.area),
                "perimeter_px": float(region.perimeter),
                "eccentricity": float(region.eccentricity),
                "solidity": float(region.solidity),
                "circularity": float(circularity),
                "cytoskeleton_coherence": float(np.mean(coh)) if coh.size else 0.0,
                "dominant_fiber_orientation_rad": float(np.mean(orient)) if orient.size else 0.0,
            })

        os.makedirs(_args["output_dir"], exist_ok=True)
        result = {
            "n_cells": len(cells),
            "cells": cells,
            "method": (
                "Otsu/mean+std threshold segmentation; shape metrics via skimage.measure.regionprops; "
                "cytoskeletal fiber alignment via structure-tensor eigenvalue coherence "
                "(OrientationJ-style) (general-purpose, not clinically validated)."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def analyze_tissue_deformation_flow(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Computes dense optical flow (Farneback's algorithm,
    ``cv2.calcOpticalFlowFarneback``) between consecutive frames of a raw
    image sequence, then derives divergence (expansion/compression) and
    vorticity (rotational flow) fields by finite-difference gradients of the
    velocity field. ``image_sequence`` is raw pixel data (not a file path),
    so no path-guard call applies to it.
    """
    args = AnalyzeTissueDeformationFlowArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = textwrap.dedent(
        """
        import os
        import numpy as np
        import cv2

        frames = [np.array(f, dtype=np.float32) for f in _args["image_sequence"]]
        pixel_scale = float(_args["pixel_scale"])

        def _norm(frame):
            fmin, fmax = float(frame.min()), float(frame.max())
            if fmax - fmin < 1e-9:
                return np.zeros_like(frame, dtype=np.uint8)
            return ((frame - fmin) / (fmax - fmin) * 255).astype(np.uint8)

        pair_metrics = []
        for i in range(len(frames) - 1):
            f0, f1 = _norm(frames[i]), _norm(frames[i + 1])
            flow = cv2.calcOpticalFlowFarneback(f0, f1, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            vx, vy = flow[..., 0] * pixel_scale, flow[..., 1] * pixel_scale
            speed = np.sqrt(vx ** 2 + vy ** 2)
            divergence = np.gradient(vx, axis=1) + np.gradient(vy, axis=0)
            vorticity = np.gradient(vy, axis=1) - np.gradient(vx, axis=0)
            pair_metrics.append({
                "frame_pair": [i, i + 1],
                "mean_speed": float(speed.mean()),
                "mean_divergence": float(divergence.mean()),
                "mean_abs_vorticity": float(np.abs(vorticity).mean()),
            })

        os.makedirs(_args["output_dir"], exist_ok=True)
        result = {
            "n_frame_pairs": len(pair_metrics),
            "pair_metrics": pair_metrics,
            "method": (
                "Dense optical flow (Farneback algorithm, cv2.calcOpticalFlowFarneback) between "
                "consecutive frames; divergence/vorticity from finite-difference gradients of the "
                "velocity field (general-purpose, not clinically validated)."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def analyze_cell_senescence_and_apoptosis(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Parses an FCS file with ``FlowIO`` and applies standard median+2SD
    quadrant gating on auto-detected Annexin-V / 7-AAD channels (live / early
    apoptotic / late apoptotic / necrotic), plus an SA-beta-Gal-style positive
    fraction if a C12FDG-like channel is present.
    """
    args = AnalyzeCellSenescenceApoptosisArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["fcs_file_path"] = ensure_safe_relative_path(validated["fcs_file_path"])

    script_body = textwrap.dedent(
        """
        import numpy as np
        import flowio

        fd = flowio.FlowData(_args["fcs_file_path"])
        n_events, n_channels = fd.event_count, fd.channel_count
        events = np.array(fd.events, dtype=float).reshape(n_events, n_channels)
        names = [fd.channels[str(i + 1)].get("PnN", "ch%d" % (i + 1)) for i in range(n_channels)]

        def _find(*keywords):
            for idx, name in enumerate(names):
                low = name.lower()
                if all(k in low for k in keywords):
                    return idx
            return None

        def _pick(*idxs):
            for i in idxs:
                if i is not None:
                    return i
            return None

        annexin_idx = _pick(_find("annexin"), _find("fitc"))
        sevenaad_idx = _pick(_find("7-aad"), _find("7aad"), _find("pe"))
        betagal_idx = _pick(_find("c12fdg"), _find("fitc"))

        def _positive_mask(idx):
            if idx is None:
                return np.zeros(n_events, dtype=bool)
            col = events[:, idx]
            thresh = np.median(col) + 2 * np.std(col)
            return col > thresh

        annexin_pos = _positive_mask(annexin_idx)
        sevenaad_pos = _positive_mask(sevenaad_idx)

        live = int(np.sum(~annexin_pos & ~sevenaad_pos))
        early_apoptotic = int(np.sum(annexin_pos & ~sevenaad_pos))
        late_apoptotic = int(np.sum(annexin_pos & sevenaad_pos))
        necrotic = int(np.sum(~annexin_pos & sevenaad_pos))

        senescent_pct = None
        if betagal_idx is not None and betagal_idx != annexin_idx:
            senescent_pct = float(_positive_mask(betagal_idx).mean() * 100)

        total = n_events
        result = {
            "n_events": total,
            "channels_used": {
                "annexin_v": names[annexin_idx] if annexin_idx is not None else None,
                "seven_aad": names[sevenaad_idx] if sevenaad_idx is not None else None,
                "beta_gal": names[betagal_idx] if betagal_idx is not None else None,
            },
            "pct_live": live / total * 100 if total else 0.0,
            "pct_early_apoptotic": early_apoptotic / total * 100 if total else 0.0,
            "pct_late_apoptotic": late_apoptotic / total * 100 if total else 0.0,
            "pct_necrotic": necrotic / total * 100 if total else 0.0,
            "pct_senescent_beta_gal": senescent_pct,
            "method": (
                "FlowIO FCS parsing + median+2SD quadrant gating on Annexin-V/7-AAD channels "
                "(standard apoptosis quadrant convention); channel auto-detection by PnN name "
                "keyword (general-purpose, not clinically validated)."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def perform_facs_cell_sorting(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Simulated FACS gating: applies a simple inclusive threshold gate
    (``[threshold_min, threshold_max]``) on the named fluorescence-parameter
    column of a pre-measured cell-suspension CSV table and writes the sorted
    subset to ``output_file``.
    """
    args = PerformFacsCellSortingArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["cell_suspension_data"] = ensure_safe_relative_path(
        validated["cell_suspension_data"]
    )
    validated["output_file"] = ensure_safe_relative_path(validated["output_file"])

    script_body = textwrap.dedent(
        """
        import os
        import pandas as pd

        df = pd.read_csv(_args["cell_suspension_data"])
        param = _args["fluorescence_parameter"]
        if param not in df.columns:
            raise ValueError(
                "fluorescence_parameter '" + param + "' not found in columns: " + str(list(df.columns))
            )

        tmin = _args.get("threshold_min")
        tmax = _args.get("threshold_max")
        mask = pd.Series(True, index=df.index)
        if tmin is not None:
            mask &= df[param] >= tmin
        if tmax is not None:
            mask &= df[param] <= tmax

        sorted_df = df[mask]
        output_file = _args["output_file"]
        out_dir = os.path.dirname(output_file)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        sorted_df.to_csv(output_file, index=False)

        result = {
            "n_total": int(len(df)),
            "n_sorted": int(len(sorted_df)),
            "purity_fraction": float(len(sorted_df) / len(df)) if len(df) else 0.0,
            "gate_min": tmin,
            "gate_max": tmax,
            "output_file": output_file,
            "method": (
                "Simulated FACS gating: simple inclusive threshold gate on the specified "
                "fluorescence-parameter column of a pre-measured cell-suspension table."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def analyze_flow_cytometry_immunophenotyping(
    arguments: Dict[str, Any], driver
) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Parses an FCS file with ``FlowIO``, optionally applies linear spillover
    compensation (``compensated = raw @ inv(compensation_matrix)^T``, the
    standard formula), then applies sequential hierarchical rectangular gating
    per ``gating_strategy`` (each gate is applied on top of the previous
    gate's surviving population).
    """
    args = AnalyzeFlowCytometryImmunophenotypingArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["fcs_file_path"] = ensure_safe_relative_path(validated["fcs_file_path"])
    validated["output_dir"] = ensure_safe_relative_path(validated["output_dir"])

    script_body = textwrap.dedent(
        """
        import os
        import numpy as np
        import flowio

        fd = flowio.FlowData(_args["fcs_file_path"])
        n_events, n_channels = fd.event_count, fd.channel_count
        events = np.array(fd.events, dtype=float).reshape(n_events, n_channels)
        names = [fd.channels[str(i + 1)].get("PnN", "ch%d" % (i + 1)) for i in range(n_channels)]
        name_to_idx = {n: i for i, n in enumerate(names)}

        comp = _args.get("compensation_matrix")
        if comp:
            comp_mat = np.array(comp, dtype=float)
            inv_comp = np.linalg.inv(comp_mat)
            k = comp_mat.shape[0]
            events[:, :k] = events[:, :k] @ inv_comp.T

        current_mask = np.ones(n_events, dtype=bool)
        gating_result = []
        for gate_name, gate in _args["gating_strategy"].items():
            channel = gate["channel"]
            if channel not in name_to_idx:
                gating_result.append({"gate": gate_name, "error": "channel '" + channel + "' not found"})
                continue
            idx = name_to_idx[channel]
            col = events[:, idx]
            gmin = gate.get("min", -np.inf)
            gmax = gate.get("max", np.inf)
            current_mask &= (col >= gmin) & (col <= gmax)
            gating_result.append({
                "gate": gate_name,
                "channel": channel,
                "n_cells": int(current_mask.sum()),
                "pct_of_total": float(current_mask.sum() / n_events * 100) if n_events else 0.0,
            })

        os.makedirs(_args["output_dir"], exist_ok=True)
        result = {
            "n_total_events": n_events,
            "channels": names,
            "gating_hierarchy": gating_result,
            "n_final_population": int(current_mask.sum()),
            "pct_final_population": float(current_mask.sum() / n_events * 100) if n_events else 0.0,
            "method": (
                "FlowIO FCS parsing; optional linear spillover compensation "
                "(compensated = raw @ inv(comp)^T); sequential hierarchical rectangular gating per "
                "the supplied gating_strategy (general-purpose, not clinically validated)."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def analyze_cfse_cell_proliferation(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier C. General-purpose scikit-image/opencv/trackpy/flowio pipeline
    -- NOT clinically or publication validated. Treat results as
    exploratory, not diagnostic.

    Parses an FCS file with ``FlowIO``, optionally gates on an FSC-A
    lymphocyte morphology gate, then detects CFSE dye-dilution generation
    peaks on a log10-fluorescence histogram (``scipy.signal.find_peaks``),
    assigns each peak a generation number by spacing relative to the
    brightest (undivided) peak, and computes the standard
    generation-weighted proliferation/division indices.
    """
    args = AnalyzeCfseCellProliferationArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["fcs_file_path"] = ensure_safe_relative_path(validated["fcs_file_path"])

    script_body = textwrap.dedent(
        """
        import numpy as np
        import flowio
        from scipy.signal import find_peaks

        fd = flowio.FlowData(_args["fcs_file_path"])
        n_events, n_channels = fd.event_count, fd.channel_count
        events = np.array(fd.events, dtype=float).reshape(n_events, n_channels)
        names = [fd.channels[str(i + 1)].get("PnN", "ch%d" % (i + 1)) for i in range(n_channels)]

        cfse_channel = _args["cfse_channel"]
        if cfse_channel not in names:
            raise ValueError("cfse_channel '" + cfse_channel + "' not found in FCS channels: " + str(names))
        cfse_idx = names.index(cfse_channel)

        lymph_gate = _args.get("lymphocyte_gate")
        mask = np.ones(n_events, dtype=bool)
        if lymph_gate is not None and "FSC-A" in names:
            fsc_idx = names.index("FSC-A")
            lo, hi = lymph_gate
            mask &= (events[:, fsc_idx] >= lo) & (events[:, fsc_idx] <= hi)

        cfse = events[mask, cfse_idx]
        cfse = cfse[cfse > 0]
        log_cfse = np.log10(cfse) if len(cfse) else np.array([])

        peaks_out = []
        if len(log_cfse):
            hist, edges = np.histogram(log_cfse, bins=60)
            peak_idx, _ = find_peaks(hist, distance=3, prominence=max(1, hist.max() * 0.02))
            peak_positions = (edges[peak_idx] + edges[peak_idx + 1]) / 2

            if len(peak_positions):
                undivided_pos = float(peak_positions.max())
                if len(peak_positions) > 1:
                    spacing = float(np.median(np.diff(np.sort(peak_positions))))
                else:
                    spacing = np.log10(2)
                spacing = spacing if spacing > 1e-6 else np.log10(2)
                generations = np.round((undivided_pos - peak_positions) / spacing).astype(int)
                generations = np.clip(generations, 0, None)
                for pos, g, cnt in zip(peak_positions, generations, hist[peak_idx]):
                    peaks_out.append({
                        "generation": int(g),
                        "log10_cfse_peak": float(pos),
                        "peak_bin_count": int(cnt),
                    })

        total_in_peaks = sum(p["peak_bin_count"] for p in peaks_out)
        if total_in_peaks:
            proliferation_index = (
                sum(p["generation"] * p["peak_bin_count"] for p in peaks_out) / total_in_peaks
            )
            precursor_weighted = sum(p["peak_bin_count"] * (2 ** p["generation"]) for p in peaks_out)
            if precursor_weighted:
                division_index = (
                    sum(
                        p["generation"] * p["peak_bin_count"] * (2 ** p["generation"])
                        for p in peaks_out
                    )
                    / precursor_weighted
                )
            else:
                division_index = 0.0
        else:
            proliferation_index = 0.0
            division_index = 0.0

        result = {
            "n_events_analyzed": int(len(cfse)),
            "n_generations_detected": len(peaks_out),
            "generation_peaks": peaks_out,
            "proliferation_index": float(proliferation_index),
            "division_index": float(division_index),
            "method": (
                "CFSE dye-dilution proliferation analysis: log10-fluorescence histogram peak "
                "detection (scipy.signal.find_peaks), generations assigned by peak spacing relative "
                "to the brightest (undivided) peak; standard generation-weighted "
                "proliferation/division index formulas (general-purpose, not clinically validated)."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def estimate_cell_cycle_phase_durations(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier B: real ``scipy.optimize.curve_fit`` numerical fit.

    Fits a 3-compartment cell-cycle ODE (G1 -> S -> G2/M -> G1, integrated via
    ``scipy.integrate.solve_ivp``) to the observed S-phase-fraction time
    course from a dual-nucleoside pulse-labeling experiment. Phase durations
    are ``1 / rate_constant``.
    """
    args = EstimateCellCyclePhaseDurationsArgs.model_validate(arguments or {})
    validated = args.model_dump()

    script_body = textwrap.dedent(
        """
        import numpy as np
        from scipy.optimize import curve_fit
        from scipy.integrate import solve_ivp

        data = _args["flow_cytometry_data"]
        init = _args["initial_estimates"]
        t_obs = np.array(data["time_points"], dtype=float)
        frac_s_obs = np.array(data.get("fraction_S", data.get("labeled_fraction")), dtype=float)

        def _model(t, k_g1, k_s, k_g2m):
            def rhs(tt, y):
                g1, s, g2m = y
                return [
                    -k_g1 * g1 + k_g2m * g2m,
                    k_g1 * g1 - k_s * s,
                    k_s * s - k_g2m * g2m,
                ]

            y0 = [1.0, 0.0, 0.0]
            sol = solve_ivp(rhs, (0, float(t.max())), y0, t_eval=np.sort(t), method="LSODA")
            order = np.argsort(np.argsort(t))
            return sol.y[1][order]

        p0 = [
            1.0 / init.get("T_G1", 10.0),
            1.0 / init.get("T_S", 8.0),
            1.0 / init.get("T_G2M", 4.0),
        ]
        popt, pcov = curve_fit(_model, t_obs, frac_s_obs, p0=p0, bounds=(1e-4, np.inf), maxfev=5000)
        k_g1, k_s, k_g2m = popt
        perr = np.sqrt(np.diag(pcov)) if pcov is not None else [None, None, None]

        result = {
            "T_G1_hours": float(1.0 / k_g1),
            "T_S_hours": float(1.0 / k_s),
            "T_G2M_hours": float(1.0 / k_g2m),
            "rate_constants": {"k_G1": float(k_g1), "k_S": float(k_s), "k_G2M": float(k_g2m)},
            "parameter_std_errors": [float(e) if e is not None else None for e in perr],
            "method": (
                "Three-compartment cell-cycle-phase ODE (G1->S->G2/M->G1) fit to the observed "
                "S-phase-fraction time course via scipy.optimize.curve_fit wrapping "
                "scipy.integrate.solve_ivp; phase duration = 1/rate constant."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


def predict_protein_disorder_regions(arguments: Dict[str, Any], driver) -> Dict[str, Any]:
    """Tier A: real, documented, cited disorder-prediction algorithm.

    Implements the **FoldIndex** algorithm (Prilusky et al. 2005,
    *Bioinformatics* 21:3435-3438): a sliding-window (51 residues)
    charge-hydropathy score ``2.785*<H> - <|R|> - 1.151`` using the
    Kyte-Doolittle hydropathy scale and net charge at pH 7 (D/E = -1,
    K/R = +1), mapped to a ``[0, 1]`` disorder probability via a logistic
    transform. This is a real, published, citable algorithm closely related
    to IUPred -- it is used here **instead of** reimplementing IUPred2A's own
    exact pairwise statistical-potential energy matrix / ANN weights, which
    are not reliably reproducible from memory here and would risk fabricating
    unverified published lookup-table constants (see this module's hard rule
    against fabricating scientific results).
    """
    args = PredictProteinDisorderRegionsArgs.model_validate(arguments or {})
    validated = args.model_dump()
    validated["output_file"] = ensure_safe_relative_path(validated["output_file"])

    script_body = textwrap.dedent(
        """
        import os
        import csv
        import numpy as np

        KD = {
            "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5,
            "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
            "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
        }
        CHARGE = {"D": -1.0, "E": -1.0, "K": 1.0, "R": 1.0}

        seq = _args["protein_sequence"]
        n = len(seq)
        window = min(51, n if n % 2 == 1 else max(1, n - 1))
        half = window // 2

        hydro = np.array([KD.get(a, 0.0) for a in seq])
        hydro_norm = (hydro + 4.5) / 9.0
        charge = np.array([CHARGE.get(a, 0.0) for a in seq])

        raw_scores = np.zeros(n)
        for i in range(n):
            lo, hi = max(0, i - half), min(n, i + half + 1)
            h_mean = float(hydro_norm[lo:hi].mean())
            r_net = abs(float(charge[lo:hi].sum())) / (hi - lo)
            raw_scores[i] = 2.785 * h_mean - r_net - 1.151

        scale = 5.0
        disorder_scores = 1.0 / (1.0 + np.exp(raw_scores * scale))
        threshold = float(_args["threshold"])
        is_disordered = disorder_scores > threshold

        segments = []
        start = None
        for i, flag in enumerate(is_disordered):
            if flag and start is None:
                start = i
            elif not flag and start is not None:
                segments.append((start + 1, i))
                start = None
        if start is not None:
            segments.append((start + 1, n))

        output_file = _args["output_file"]
        out_dir = os.path.dirname(output_file)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_file, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["position", "residue", "disorder_score", "is_disordered"])
            for i, a in enumerate(seq):
                writer.writerow([i + 1, a, "%.4f" % disorder_scores[i], bool(is_disordered[i])])

        result = {
            "length": n,
            "pct_disordered": float(is_disordered.mean() * 100) if n else 0.0,
            "disordered_segments": [{"start": s, "end": e} for s, e in segments],
            "per_residue_scores": [float(x) for x in disorder_scores],
            "output_file": output_file,
            "method": (
                "FoldIndex algorithm (Prilusky et al. 2005, Bioinformatics 21:3435-3438): "
                "sliding-window (51 residues) charge-hydropathy score = 2.785*<H>-<|R|>-1.151 using "
                "the Kyte-Doolittle hydropathy scale and net charge at pH7 (D/E=-1, K/R=+1), mapped "
                "to a [0,1] disorder probability via a logistic transform. Documented, real algorithm "
                "closely related to (but not a reimplementation of) IUPred2A's statistical-potential/"
                "ANN scoring."
            ),
        }
        print(_json.dumps(result))
        """
    )
    return run_in_sandbox(driver, script_body=script_body, args=validated)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_cell_imaging_tools(registry, driver) -> List[str]:
    """Registers every "Cell biology & imaging" action tool into ``registry``.

    Unlike ``bio_direct_adapters.py::register_direct_bio_tools`` (which takes
    an optional injected HTTP client), every handler here needs a sandbox
    driver, so ``driver`` is a required positional argument -- the same
    ``BubblewrapSandboxDriver`` instance the rest of Fase 5's action tools and
    ``SandboxNodeExecutor`` share. Each handler is bound to ``driver`` via a
    closure so the registry's single-argument ``(arguments) -> result``
    handler contract (see ``MCPServerRegistry.register_server``) is
    satisfied. Returns the list of registered tool names.
    """
    handlers = {
        "analyze_cell_migration_metrics": analyze_cell_migration_metrics,
        "analyze_calcium_imaging_data": analyze_calcium_imaging_data,
        "analyze_myofiber_morphology": analyze_myofiber_morphology,
        "quantify_cell_cycle_phases_from_microscopy": quantify_cell_cycle_phases_from_microscopy,
        "quantify_and_cluster_cell_motility": quantify_and_cluster_cell_motility,
        "analyze_mitochondrial_morphology_and_potential": (
            analyze_mitochondrial_morphology_and_potential
        ),
        "analyze_cell_morphology_and_cytoskeleton": analyze_cell_morphology_and_cytoskeleton,
        "analyze_tissue_deformation_flow": analyze_tissue_deformation_flow,
        "analyze_cell_senescence_and_apoptosis": analyze_cell_senescence_and_apoptosis,
        "perform_facs_cell_sorting": perform_facs_cell_sorting,
        "analyze_flow_cytometry_immunophenotyping": analyze_flow_cytometry_immunophenotyping,
        "analyze_cfse_cell_proliferation": analyze_cfse_cell_proliferation,
        "estimate_cell_cycle_phase_durations": estimate_cell_cycle_phase_durations,
        "predict_protein_disorder_regions": predict_protein_disorder_regions,
    }
    for name, handler in handlers.items():
        registry.register_server(name, (lambda arguments, _h=handler: _h(arguments, driver)))
    return list(handlers.keys())
