"""Iterative residual-overlay refinement.

Compares a rasterized version of the candidate SVG against the original image,
extracts the differing regions, vectorizes only those pixels with VTracer, and
appends the corrective paths to the SVG. Repeats until the DinoScore plateaus.

Each pass cycles through a different (threshold, VTracer params) variant so the
loop attacks the residual from multiple angles and keeps making progress on
fine-grained details (e.g. letter counters, anti-aliased curves).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from app.config import get_settings
from app.services import vtracer_engine
from app.services.dino_score import score_svg
from app.services.svg_raster import rasterize_svg

logger = logging.getLogger(__name__)


@dataclass
class _Variant:
    """One refinement strategy: how aggressive the diff is + how VTracer traces it.

    `edge_exclusion`: pixels within this many px of a base-render edge are dropped
    from the residual mask (suppresses anti-aliasing halo, keeps deep-interior diffs).
    `min_component_area`: minimum connected-component area (px) kept in the mask;
    smaller fragments are noise. `min_thickness`: morphological-erode size used to
    require a minimum stroke width before VTracer ever sees the residual.
    """

    threshold_factor: float
    edge_exclusion: int = 2
    min_component_area: int = 24
    min_thickness: int = 1
    vtracer: dict = field(default_factory=dict)


# Variants progress from "looks for big interior defects" to "looks for fine-grained
# near-edge defects". Earlier overly-aggressive filters (`edge_exclusion=3`) wiped
# out everything on text-heavy logos where every defect IS edge-like, so we now use
# moderate `edge_exclusion` and rely more on `min_component_area` to drop noise.
_PASS_VARIANTS: tuple[_Variant, ...] = (
    _Variant(
        threshold_factor=0.7,
        edge_exclusion=2,
        min_component_area=48,
        min_thickness=1,
        vtracer={
            "colormode": "color",
            "hierarchical": "stacked",
            "mode": "spline",
            "filter_speckle": 4,
            "path_precision": 8,
            "color_precision": 6,
        },
    ),
    _Variant(
        threshold_factor=1.0,
        edge_exclusion=2,
        min_component_area=32,
        min_thickness=1,
        vtracer={
            "colormode": "color",
            "hierarchical": "stacked",
            "mode": "spline",
            "filter_speckle": 2,
            "path_precision": 8,
            "color_precision": 6,
        },
    ),
    _Variant(
        threshold_factor=0.8,
        edge_exclusion=1,
        min_component_area=24,
        min_thickness=1,
        vtracer={
            "colormode": "color",
            "hierarchical": "cutout",
            "mode": "spline",
            "filter_speckle": 2,
            "path_precision": 8,
            "color_precision": 8,
        },
    ),
    _Variant(
        threshold_factor=0.65,
        edge_exclusion=1,
        min_component_area=16,
        min_thickness=1,
        vtracer={
            "colormode": "color",
            "hierarchical": "stacked",
            "mode": "polygon",
            "filter_speckle": 2,
            "path_precision": 8,
            "color_precision": 4,
        },
    ),
    _Variant(
        threshold_factor=0.5,
        edge_exclusion=1,
        min_component_area=12,
        min_thickness=1,
        vtracer={
            "colormode": "color",
            "hierarchical": "stacked",
            "mode": "spline",
            "filter_speckle": 1,
            "path_precision": 8,
            "color_precision": 8,
        },
    ),
    _Variant(
        threshold_factor=0.4,
        edge_exclusion=0,
        min_component_area=8,
        min_thickness=1,
        vtracer={
            "colormode": "binary",
            "hierarchical": "stacked",
            "mode": "spline",
            "filter_speckle": 1,
            "path_precision": 8,
            "color_precision": 4,
        },
    ),
)


@dataclass
class RefineResult:
    svg: str
    score: float
    passes: int
    coverage: float


def residual_mask(
    original: np.ndarray,
    rendered: np.ndarray,
    threshold: int = 14,
    *,
    edge_exclusion: int = 2,
    min_component_area: int = 24,
    min_thickness: int = 1,
) -> np.ndarray:
    """Boolean mask of pixels where `rendered` meaningfully differs from `original`.

    Built specifically for residual-overlay refinement, so it tries to drop the two
    big sources of false-positive corrections:

    * **Anti-aliasing halo** along every edge of the rendered SVG. Without filtering,
      a thin shell of "wrong" pixels surrounds every shape boundary and dominates
      the mask. We compute edges of the rendered image, dilate them by
      `edge_exclusion` pixels, and remove those pixels from the mask. Real defects
      (a malformed letter counter, a missing dot) are *interior* regions far from
      the base-edge skeleton, so they survive.
    * **Speckle noise**. Connected components below `min_component_area` are dropped.

    `min_thickness` lets the caller require a minimum stroke width via an extra
    erosion pass (default 1 = no extra erosion).
    """
    if original.ndim == 2:
        original = np.stack([original] * 3, axis=-1)
    if rendered.ndim == 2:
        rendered = np.stack([rendered] * 3, axis=-1)

    o = original[..., :3]
    r = rendered[..., :3]
    if o.shape != r.shape:
        r = cv2.resize(r, (o.shape[1], o.shape[0]), interpolation=cv2.INTER_AREA)

    diff = np.abs(o.astype(np.int16) - r.astype(np.int16)).max(axis=2)
    mask = (diff > threshold).astype(np.uint8) * 255

    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)

    if edge_exclusion > 0:
        rendered_gray = cv2.cvtColor(r, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(rendered_gray, 40, 120)
        if edge_exclusion > 1:
            dilate_size = 2 * edge_exclusion + 1
            dilate_kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (dilate_size, dilate_size)
            )
            edges = cv2.dilate(edges, dilate_kernel)
        mask[edges > 0] = 0

    if min_thickness > 1:
        erode_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (min_thickness, min_thickness)
        )
        mask = cv2.erode(mask, erode_kernel)

    if min_component_area > 0 and mask.any():
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        keep = np.zeros_like(mask)
        for label in range(1, num_labels):
            if stats[label, cv2.CC_STAT_AREA] >= min_component_area:
                keep[labels == label] = 255
        mask = keep

    return mask > 0


def make_residual_rgba(original: Image.Image, mask: np.ndarray) -> Image.Image:
    """Return RGBA image with original pixels where mask is True, transparent elsewhere."""
    rgba = original.convert("RGBA")
    arr = np.array(rgba)
    if arr.shape[:2] != mask.shape:
        mask = (
            cv2.resize(
                mask.astype(np.uint8),
                (arr.shape[1], arr.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            ).astype(bool)
        )
    arr[..., 3] = np.where(mask, 255, 0).astype(np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def vectorize_residual(rgba: Image.Image, **params) -> str:
    """Trace only the non-transparent regions with high path precision."""
    defaults = {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "filter_speckle": 2,
        "path_precision": 8,
        "color_precision": 6,
    }
    defaults.update(params)
    return vtracer_engine.vectorize(rgba, **defaults)


_SVG_BODY_RE = re.compile(r"<svg\b[^>]*>(.*)</svg>", re.DOTALL | re.IGNORECASE)
_VIEWBOX_RE = re.compile(r'\bviewBox\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_viewbox(svg: str) -> tuple[float, float, float, float] | None:
    """Return (x, y, w, h) for the root `<svg>` viewBox, or fall back to width/height.

    StarVector often emits normalized `viewBox="0 0 1 1"` while VTracer's residual
    output uses pixel units. Without a transform the overlay would land outside the
    base canvas — so the merger uses these to compute a matrix that maps overlay
    user units into base user units.
    """
    open_match = _SVG_OPEN_RE.search(svg)
    if not open_match:
        return None
    open_tag = open_match.group(0)

    vb_match = _VIEWBOX_RE.search(open_tag)
    if vb_match:
        parts = _NUM_RE.findall(vb_match.group(1))
        if len(parts) == 4:
            try:
                x, y, w, h = (float(p) for p in parts)
                if w > 0 and h > 0:
                    return (x, y, w, h)
            except ValueError:
                pass

    w_match = re.search(r'\swidth\s*=\s*["\']([^"\']+)["\']', open_tag, re.IGNORECASE)
    h_match = re.search(r'\sheight\s*=\s*["\']([^"\']+)["\']', open_tag, re.IGNORECASE)
    if w_match and h_match:
        try:
            w_nums = _NUM_RE.findall(w_match.group(1))
            h_nums = _NUM_RE.findall(h_match.group(1))
            if w_nums and h_nums:
                w = float(w_nums[0])
                h = float(h_nums[0])
                if w > 0 and h > 0:
                    return (0.0, 0.0, w, h)
        except ValueError:
            pass
    return None


def _format_num(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def merge_overlay(base_svg: str, overlay_svg: str) -> str:
    """Append paths from `overlay_svg` to the body of `base_svg`, mapping coords.

    If the two SVGs use different `viewBox` user units (very common between
    StarVector and VTracer), the overlay is wrapped in a `<g transform="matrix(...)">`
    that maps overlay user units into base user units so the corrective paths
    land in the right place.
    """
    match = _SVG_BODY_RE.search(overlay_svg)
    if not match:
        return base_svg
    body = match.group(1).strip()
    if not body:
        return base_svg

    body = re.sub(r"<\?xml[^>]*\?>", "", body)
    body = re.sub(r"<!DOCTYPE[^>]*>", "", body)

    base_vb = _parse_viewbox(base_svg)
    overlay_vb = _parse_viewbox(overlay_svg)
    transform_attr = ""
    if base_vb and overlay_vb and base_vb != overlay_vb:
        bx, by, bw, bh = base_vb
        ox, oy, ow, oh = overlay_vb
        sx = bw / ow
        sy = bh / oh
        tx = bx - ox * sx
        ty = by - oy * sy
        transform_attr = (
            f' transform="matrix({_format_num(sx)} 0 0 {_format_num(sy)} '
            f'{_format_num(tx)} {_format_num(ty)})"'
        )

    overlay_group = f'<g class="vb-refine"{transform_attr}>{body}</g>'
    insert_at = base_svg.rfind("</svg>")
    if insert_at == -1:
        return base_svg
    return base_svg[:insert_at] + overlay_group + base_svg[insert_at:]


def iterative_refine(
    original: Image.Image,
    base_svg: str,
    width: int,
    height: int,
    *,
    max_passes: int | None = None,
    min_delta: float | None = None,
    min_mask_ratio: float | None = None,
    threshold: int | None = None,
) -> RefineResult:
    """Repeatedly diff-and-patch the SVG until the score plateaus.

    Each iteration:
    1. Rasterize the current best SVG.
    2. Compute pixel residual against the original.
    3. Mask significant differences; bail if too small.
    4. Vectorize the residual with the next parameter variant.
    5. Merge into a candidate SVG and re-score.
    6. Accept if score improved by at least `min_delta`; otherwise count a
       rejection and try the next variant. After every variant has been tried
       without an acceptance, stop.
    """
    settings = get_settings()
    max_passes = max_passes if max_passes is not None else settings.refine_max_passes
    min_delta = min_delta if min_delta is not None else settings.refine_min_delta
    min_mask_ratio = (
        min_mask_ratio if min_mask_ratio is not None else settings.refine_min_mask_ratio
    )
    base_threshold = (
        threshold if threshold is not None else settings.refine_residual_threshold
    )

    if max_passes <= 0 or not settings.refine_enabled:
        score, _ = score_svg(original, base_svg, width, height)
        return RefineResult(svg=base_svg, score=score, passes=0, coverage=0.0)

    original_rgb = np.array(original.convert("RGB"))
    best_svg = base_svg
    best_score, _ = score_svg(original, best_svg, width, height)
    initial_score = best_score
    total_coverage = 0.0
    accepted = 0
    consecutive_empty = 0
    rejections_since_accept = 0
    overlay_attempts = 0
    total_variants = len(_PASS_VARIANTS)

    for pass_idx in range(max_passes):
        variant_idx = pass_idx % total_variants
        variant = _PASS_VARIANTS[variant_idx]
        threshold_eff = max(4, int(round(base_threshold * variant.threshold_factor)))

        try:
            rendered = rasterize_svg(best_svg, width, height)
        except Exception as exc:
            logger.warning("refine pass %d: rasterize failed: %s", pass_idx + 1, exc)
            break

        rendered_arr = np.array(rendered.convert("RGB"))
        mask = residual_mask(
            original_rgb,
            rendered_arr,
            threshold=threshold_eff,
            edge_exclusion=variant.edge_exclusion,
            min_component_area=variant.min_component_area,
            min_thickness=variant.min_thickness,
        )
        coverage = float(mask.sum()) / float(mask.size)

        if coverage < min_mask_ratio:
            consecutive_empty += 1
            logger.info(
                "refine pass %d (variant %d, threshold %d): mask coverage %.4f "
                "below %.4f after edge/area filters, skipping",
                pass_idx + 1,
                variant_idx,
                threshold_eff,
                coverage,
                min_mask_ratio,
            )
            if consecutive_empty >= total_variants:
                logger.info(
                    "refine: cycled through all %d variants with empty masks, "
                    "no further refinement possible (base score %.4f)",
                    total_variants,
                    best_score,
                )
                break
            continue
        consecutive_empty = 0

        residual = make_residual_rgba(original, mask)
        try:
            overlay_svg = vectorize_residual(residual, **variant.vtracer)
        except Exception as exc:
            logger.warning(
                "refine pass %d: vectorize_residual failed: %s", pass_idx + 1, exc
            )
            rejections_since_accept += 1
            if rejections_since_accept >= total_variants:
                break
            continue

        overlay_attempts += 1
        merged = merge_overlay(best_svg, overlay_svg)
        try:
            new_score, _ = score_svg(original, merged, width, height)
        except Exception as exc:
            logger.warning("refine pass %d: scoring failed: %s", pass_idx + 1, exc)
            rejections_since_accept += 1
            if rejections_since_accept >= total_variants:
                break
            continue

        delta = new_score - best_score
        if delta >= min_delta:
            best_svg = merged
            best_score = new_score
            total_coverage = max(total_coverage, coverage)
            accepted += 1
            rejections_since_accept = 0
            logger.info(
                "refine pass %d (variant %d, threshold %d): accepted "
                "score=%.4f delta=%.4f coverage=%.3f",
                pass_idx + 1,
                variant_idx,
                threshold_eff,
                best_score,
                delta,
                coverage,
            )
        else:
            rejections_since_accept += 1
            logger.info(
                "refine pass %d (variant %d, threshold %d): rejected "
                "delta=%.4f (best=%.4f) rejections=%d/%d",
                pass_idx + 1,
                variant_idx,
                threshold_eff,
                delta,
                best_score,
                rejections_since_accept,
                total_variants,
            )
            if rejections_since_accept >= total_variants:
                logger.info(
                    "refine: all %d variants tried without improvement, stopping",
                    total_variants,
                )
                break

    if accepted == 0 and overlay_attempts > 0:
        logger.info(
            "refine: no overlay improved the score; base output kept (score %.4f). "
            "%d overlay attempt(s) were merged and scored but worsened or did not "
            "beat the base (remaining defects may be edge-adjacent geometry the "
            "residual-overlay pass cannot patch cleanly).",
            initial_score,
            overlay_attempts,
        )
    elif accepted == 0:
        logger.info(
            "refine: no overlay improved the score; base output kept (score %.4f). "
            "Remaining diff is likely sub-pixel anti-aliasing or was filtered out "
            "by edge/area masks.",
            initial_score,
        )

    return RefineResult(
        svg=best_svg,
        score=best_score,
        passes=accepted,
        coverage=total_coverage,
    )
