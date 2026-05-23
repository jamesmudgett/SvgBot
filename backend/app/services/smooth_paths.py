"""Geometric smoothing post-process for the chosen SVG.

Two complementary methods, picked by the hybrid ``smooth_svg`` entry point:

- **Approach B (supersample-retrace):** rasterize at ``scale * (w, h)``, apply
  a small Gaussian blur to damp pixel-step ramps in the rendered AA, then
  re-trace with VTracer in ``mode=spline``. Cheap, reuses existing tools.
- **Approach A (Schneider Bezier refit):** polyline-sample every path's ``d``,
  mark turn-angle corners, refit smooth cubic Beziers between consecutive
  corners. Corner-preserving by construction.

``smooth_svg`` tries B first; if B's output fails the DinoScore gate or the
corner-preservation histogram check, it falls back to A. If both fail the
input SVG is returned with ``method='none'``.

The cleo regression: VTracer's vtracer_mono output for the cleo logo is a
chain of stair-stepped micro line segments along every letter contour. No
amount of re-ranking will fix that; we have to rewrite the geometry.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Callable, Sequence

import cv2
import numpy as np
from PIL import Image

from app.config import Settings
from app.services import vtracer_engine
from app.services.svg_raster import rasterize_svg

logger = logging.getLogger(__name__)

_PATH_D_RE = re.compile(
    r'(<path\b[^>]*\bd\s*=\s*)(["\'])(.*?)(\2)', re.IGNORECASE | re.DOTALL
)
_PATH_TAG_RE = re.compile(r"<path\b[^>]*>", re.IGNORECASE)
_VIEWBOX_RE = re.compile(r'\sviewBox\s*=\s*"([^"]*)"', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def smooth_svg(
    svg: str,
    width: int,
    height: int,
    *,
    kind: str,
    score_fn: Callable[[str], float],
    settings: Settings,
) -> tuple[str, str, float]:
    """Run the hybrid smoothing pass and return ``(svg, method, dino_delta)``.

    ``method`` is ``'supersample'`` when Approach B was accepted,
    ``'bezier_refit'`` when Approach A was accepted, or ``'none'`` when both
    failed (input is returned byte-for-byte).
    """
    base_dino = score_fn(svg)
    max_delta = float(settings.path_smoothing_max_delta)
    corner_angle = float(settings.path_smoothing_corner_angle_deg)
    retention = float(settings.path_smoothing_corner_retention_threshold)

    rdp_tolerance = _rdp_tolerance_for_kind(kind, settings)
    scale = int(settings.path_smoothing_supersample_scale)
    blur_sigma = float(settings.path_smoothing_blur_sigma)
    if kind == "illustration":
        scale = max(2, scale - 1)
        blur_sigma = max(0.0, blur_sigma - 0.2)

    # --- Approach B: supersample-retrace -----------------------------------
    try:
        b_svg = _smooth_via_supersample(
            svg, width, height, scale=scale, blur_sigma=blur_sigma,
            max_dimension=int(settings.max_image_dimension),
        )
    except Exception as exc:
        logger.warning("smooth_paths: supersample failed: %s", exc)
        b_svg = None

    if b_svg is not None:
        try:
            b_dino = score_fn(b_svg)
        except Exception as exc:
            logger.warning("smooth_paths: scoring B failed: %s", exc)
            b_dino = -math.inf
        b_score_ok = b_dino >= base_dino - max_delta
        b_corners_ok = _preserves_corners(
            svg, b_svg,
            corner_angle_deg=corner_angle, retention_threshold=retention,
        )
        if b_score_ok and b_corners_ok:
            return b_svg, "supersample", b_dino - base_dino
        logger.info(
            "smooth_paths: B rejected (score_ok=%s corners_ok=%s "
            "dino %.4f vs %.4f); falling back to bezier refit",
            b_score_ok, b_corners_ok, b_dino, base_dino,
        )

    # --- Approach A: Schneider Bezier refit --------------------------------
    try:
        a_svg = _smooth_via_bezier_refit(
            svg,
            corner_angle_deg=corner_angle,
            rdp_tolerance=rdp_tolerance,
            sample_step=0.6,
        )
    except Exception as exc:
        logger.warning("smooth_paths: bezier refit failed: %s", exc)
        return svg, "none", 0.0

    if a_svg == svg:
        return svg, "none", 0.0

    try:
        a_dino = score_fn(a_svg)
    except Exception as exc:
        logger.warning("smooth_paths: scoring A failed: %s", exc)
        return svg, "none", 0.0

    if a_dino >= base_dino - max_delta:
        return a_svg, "bezier_refit", a_dino - base_dino

    logger.info(
        "smooth_paths: A rejected (dino %.4f vs %.4f, delta %+.4f below "
        "tolerance %.4f); keeping refined SVG",
        a_dino, base_dino, a_dino - base_dino, max_delta,
    )
    return svg, "none", 0.0


def _rdp_tolerance_for_kind(kind: str, settings: Settings) -> float:
    if kind == "illustration":
        return float(settings.path_smoothing_rdp_tolerance_illustration)
    return float(settings.path_smoothing_rdp_tolerance_logo)


# ---------------------------------------------------------------------------
# Approach B: supersample-retrace
# ---------------------------------------------------------------------------


def _smooth_via_supersample(
    svg: str,
    width: int,
    height: int,
    *,
    scale: int = 4,
    blur_sigma: float = 0.7,
    max_dimension: int = 2048,
    vtracer_params: dict | None = None,
) -> str:
    """Rasterize at ``scale * (w, h)``, blur, re-trace, renormalize viewBox.

    The returned SVG always has ``viewBox="0 0 {width} {height}"`` regardless
    of the scale used for tracing, so downstream consumers see the original
    coordinate space.
    """
    longest = max(width, height)
    if longest <= 0:
        raise ValueError("width and height must be positive")

    max_scale = max(1, max_dimension // longest)
    eff_scale = max(1, min(int(scale), max_scale))
    new_w = max(1, width * eff_scale)
    new_h = max(1, height * eff_scale)

    hi = rasterize_svg(svg, new_w, new_h)
    arr = np.array(hi.convert("RGB"))
    if blur_sigma > 0:
        arr = cv2.GaussianBlur(arr, ksize=(0, 0), sigmaX=float(blur_sigma))
    img = Image.fromarray(arr, mode="RGB")

    params = {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "filter_speckle": 6,
        "color_precision": 5,
        "path_precision": 6,
        "corner_threshold": 80,
        "length_threshold": 6.0,
        "splice_threshold": 65,
    }
    if vtracer_params:
        params.update(vtracer_params)

    traced = vtracer_engine.vectorize(img, **params)
    return _renormalize_viewbox(traced, width, height, eff_scale)


def _renormalize_viewbox(
    svg: str, target_w: int, target_h: int, scale: int
) -> str:
    """Force the root viewBox/width/height to the target dims.

    VTracer emits paths in the pixel coord space of the input image, so when
    we trace at ``scale * size`` the resulting SVG has paths in scaled
    coordinates. We rewrap the body in ``<g transform="scale(1/scale)">`` and
    overwrite the root attrs so the output displays at the target size.
    """
    open_match = re.search(r"<svg\b[^>]*>", svg, re.IGNORECASE)
    if not open_match:
        return svg
    open_tag = open_match.group(0)

    new_open = re.sub(r'\sviewBox\s*=\s*"[^"]*"', "", open_tag, flags=re.IGNORECASE)
    new_open = re.sub(r"\swidth\s*=\s*\"[^\"]*\"", "", new_open, flags=re.IGNORECASE)
    new_open = re.sub(r"\sheight\s*=\s*\"[^\"]*\"", "", new_open, flags=re.IGNORECASE)
    new_open = (
        new_open[:-1]
        + f' viewBox="0 0 {target_w} {target_h}" '
        + f'width="{target_w}" height="{target_h}">'
    )

    body_start = open_match.end()
    body_end = svg.rfind("</svg>")
    if body_end == -1:
        return svg
    body = svg[body_start:body_end]

    if scale != 1:
        inv = 1.0 / float(scale)
        body = f'<g transform="scale({inv:.6f})">{body}</g>'

    return svg[: open_match.start()] + new_open + body + "</svg>"


# ---------------------------------------------------------------------------
# Approach A: Schneider Bezier refit
# ---------------------------------------------------------------------------


def _smooth_via_bezier_refit(
    svg: str,
    *,
    corner_angle_deg: float = 75.0,
    rdp_tolerance: float = 0.35,
    sample_step: float = 0.6,
) -> str:
    """Rewrite every ``<path d="...">`` with corner-preserving smooth Beziers.

    Algorithm per path:

    1. Parse ``d`` with svgpathtools.
    2. Split into subpaths at every ``M`` / closepath.
    3. For each subpath, polyline-sample at ``sample_step`` user units.
    4. Mark vertices with turn angle > ``corner_angle_deg`` as corners.
    5. Between consecutive corners, run Ramer-Douglas-Peucker and fit a chain
       of cubic Beziers with Schneider's algorithm.
    6. Reassemble the new ``d``.

    If any step fails for a given path, the original ``d`` is preserved.
    """

    def _rewrite(match: re.Match) -> str:
        prefix, quote, d_attr, _ = match.groups()
        new_d = _refit_path_d(
            d_attr,
            corner_angle_deg=corner_angle_deg,
            rdp_tolerance=rdp_tolerance,
            sample_step=sample_step,
        )
        if new_d is None or not new_d.strip():
            return match.group(0)
        return f"{prefix}{quote}{new_d}{quote}"

    return _PATH_D_RE.sub(_rewrite, svg)


def _refit_path_d(
    d: str,
    *,
    corner_angle_deg: float,
    rdp_tolerance: float,
    sample_step: float,
) -> str | None:
    """Refit a single ``d`` attribute. Returns ``None`` to signal 'leave it'."""
    try:
        from svgpathtools import parse_path
    except Exception as exc:
        logger.warning("svgpathtools unavailable: %s", exc)
        return None

    try:
        path = parse_path(d)
    except Exception:
        return None
    if not path:
        return None

    subpaths = _split_into_subpaths(path)
    if not subpaths:
        return None

    out_parts: list[str] = []
    for sub, closed in subpaths:
        polyline = _sample_polyline(sub, step=sample_step)
        if polyline is None or len(polyline) < 4:
            out_parts.append(_emit_polyline(polyline, closed=closed))
            continue
        # RDP must run *before* corner detection. A pixel-stepped polyline is
        # geometrically a chain of 90 deg corners; without RDP, the corner
        # detector would flag every step as a corner and the refit would emit
        # one Bezier per step (= no smoothing). RDP collapses the steps into a
        # smooth diagonal first, then corner detection finds only "real"
        # corners on the simplified polyline (letter terminals, etc.).
        simplified = _rdp(polyline, rdp_tolerance)
        if len(simplified) < 4:
            out_parts.append(
                _emit_smoothed_segments(
                    [(simplified, False)],
                    closed=closed,
                    bezier_max_error=rdp_tolerance,
                )
            )
            continue
        corners = _find_corners(
            simplified, angle_threshold_deg=corner_angle_deg, closed=closed
        )
        segments = _split_at_corners(simplified, corners, closed=closed)
        emitted = _emit_smoothed_segments(
            segments, closed=closed, bezier_max_error=rdp_tolerance
        )
        out_parts.append(emitted)
    return " ".join(p for p in out_parts if p)


def _split_into_subpaths(path) -> list[tuple[list, bool]]:
    """Split an svgpathtools Path into contiguous subpaths.

    Returns ``[(segments, closed)]`` where ``segments`` is a list of
    svgpathtools segment objects and ``closed`` is True iff the subpath ends
    at the same point it started.
    """
    out: list[tuple[list, bool]] = []
    cur: list = []
    for seg in path:
        if cur and abs(complex(cur[-1].end) - complex(seg.start)) > 1e-6:
            closed = abs(complex(cur[0].start) - complex(cur[-1].end)) < 1e-3
            out.append((cur, closed))
            cur = []
        cur.append(seg)
    if cur:
        closed = abs(complex(cur[0].start) - complex(cur[-1].end)) < 1e-3
        out.append((cur, closed))
    return out


def _sample_polyline(segments: list, *, step: float = 0.6) -> np.ndarray | None:
    """Sample a list of svgpathtools segments into a dense polyline.

    Returns an (N, 2) array of (x, y). The number of samples per segment is
    proportional to its arc length so curved segments get more points.
    """
    pts: list[tuple[float, float]] = []
    for seg in segments:
        try:
            length = float(seg.length())
        except Exception:
            length = 0.0
        n = max(2, int(math.ceil(length / max(step, 0.05))))
        for i in range(n + 1):
            t = i / n
            try:
                p = seg.point(t)
            except Exception:
                continue
            pts.append((p.real, p.imag))
    if not pts:
        return None
    arr = np.asarray(pts, dtype=np.float64)
    # Collapse runs of duplicate / near-duplicate points.
    deltas = np.linalg.norm(np.diff(arr, axis=0), axis=1)
    keep = np.concatenate([[True], deltas > 1e-6])
    arr = arr[keep]
    return arr if len(arr) >= 2 else None


def _find_corners(
    polyline: np.ndarray, *, angle_threshold_deg: float, closed: bool
) -> list[int]:
    """Return indices of vertices whose turn angle exceeds the threshold."""
    if len(polyline) < 3:
        return []
    threshold = math.radians(angle_threshold_deg)
    corners: list[int] = []
    n = len(polyline)
    for i in range(1, n - 1):
        a = polyline[i] - polyline[i - 1]
        b = polyline[i + 1] - polyline[i]
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-9 or nb < 1e-9:
            continue
        cos_t = float(np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0))
        # Turn angle: 0 means straight, pi means u-turn.
        turn = math.acos(cos_t)
        if turn >= threshold:
            corners.append(i)
    # For closed polylines, also check the seam.
    if closed and n >= 3:
        a = polyline[0] - polyline[-2]
        b = polyline[1] - polyline[0]
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na > 1e-9 and nb > 1e-9:
            cos_t = float(np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0))
            if math.acos(cos_t) >= threshold:
                corners.append(0)
    return sorted(set(corners))


def _split_at_corners(
    polyline: np.ndarray, corners: list[int], *, closed: bool
) -> list[tuple[np.ndarray, bool]]:
    """Split the polyline into smooth segments between corners.

    Each segment is ``(points, was_at_seam)`` where points includes both the
    starting corner and the ending corner (so adjacent segments share a
    corner vertex, which becomes a path break in the output).
    """
    n = len(polyline)
    if not corners:
        return [(polyline, False)]

    segments: list[tuple[np.ndarray, bool]] = []
    if closed:
        idxs = corners
        for i in range(len(idxs)):
            start = idxs[i]
            end = idxs[(i + 1) % len(idxs)]
            if end > start:
                seg = polyline[start : end + 1]
            else:
                seg = np.concatenate([polyline[start:], polyline[1 : end + 1]])
            if len(seg) >= 2:
                segments.append((seg, i == len(idxs) - 1))
    else:
        boundaries = [0] + corners + [n - 1]
        for i in range(len(boundaries) - 1):
            seg = polyline[boundaries[i] : boundaries[i + 1] + 1]
            if len(seg) >= 2:
                segments.append((seg, False))
    return segments


def _rdp(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Ramer-Douglas-Peucker simplification."""
    if len(points) < 3:
        return points
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        seg_start = points[i]
        seg_end = points[j]
        d = seg_end - seg_start
        norm = np.linalg.norm(d)
        if norm < 1e-9:
            dists = np.linalg.norm(points[i + 1 : j] - seg_start, axis=1)
        else:
            n = np.array([-d[1], d[0]]) / norm
            offsets = points[i + 1 : j] - seg_start
            dists = np.abs(offsets @ n)
        if len(dists) == 0:
            continue
        local = int(np.argmax(dists))
        if dists[local] > tolerance:
            mid = i + 1 + local
            keep[mid] = True
            stack.append((i, mid))
            stack.append((mid, j))
    return points[keep]


def _emit_polyline(points: np.ndarray | None, *, closed: bool) -> str:
    if points is None or len(points) < 2:
        return ""
    parts = [f"M {_fmt(points[0, 0])} {_fmt(points[0, 1])}"]
    for p in points[1:]:
        parts.append(f"L {_fmt(p[0])} {_fmt(p[1])}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def _emit_smoothed_segments(
    segments: Sequence[tuple[np.ndarray, bool]],
    *,
    closed: bool,
    bezier_max_error: float,
) -> str:
    """Emit a single ``d`` substring covering all smooth segments.

    Each segment was already RDP-simplified upstream; here we just fit cubic
    Beziers with Schneider's algorithm. Adjacent segments share endpoints
    (corners), which naturally become breaks (no curvature continuity is
    forced across them).
    """
    parts: list[str] = []
    started = False
    for points, _seam in segments:
        if points is None or len(points) < 2:
            continue
        if not started:
            parts.append(f"M {_fmt(points[0, 0])} {_fmt(points[0, 1])}")
            started = True
        else:
            parts.append(f"L {_fmt(points[0, 0])} {_fmt(points[0, 1])}")

        if len(points) == 2:
            parts.append(f"L {_fmt(points[1, 0])} {_fmt(points[1, 1])}")
            continue

        beziers = _fit_bezier_chain(points, max_error=max(bezier_max_error, 0.5))
        for _p0, p1, p2, p3 in beziers:
            parts.append(
                f"C {_fmt(p1[0])} {_fmt(p1[1])} "
                f"{_fmt(p2[0])} {_fmt(p2[1])} "
                f"{_fmt(p3[0])} {_fmt(p3[1])}"
            )
    if closed and parts:
        parts.append("Z")
    return " ".join(parts)


# ---- Schneider's algorithm ------------------------------------------------


def _fit_bezier_chain(
    points: np.ndarray, *, max_error: float, max_depth: int = 10
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Fit a chain of cubic Beziers to ``points`` using Schneider's algorithm."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 2:
        return []
    if len(pts) == 2:
        # Degenerate: emit a straight line as a degenerate Bezier
        p0, p3 = pts[0], pts[1]
        d = (p3 - p0) / 3.0
        return [(p0, p0 + d, p0 + 2 * d, p3)]

    left_tan = _unit(pts[1] - pts[0])
    right_tan = _unit(pts[-2] - pts[-1])
    return _fit_recursive(pts, left_tan, right_tan, max_error, max_depth)


def _fit_recursive(
    pts: np.ndarray,
    left_tan: np.ndarray,
    right_tan: np.ndarray,
    max_error: float,
    depth: int,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    bezier = _fit_one_bezier(pts, left_tan, right_tan)
    err, split_idx = _max_error(pts, bezier)
    if err < max_error or depth <= 0 or split_idx <= 0 or split_idx >= len(pts) - 1:
        return [bezier]

    center_tan = _unit(pts[split_idx - 1] - pts[split_idx + 1])
    left = _fit_recursive(
        pts[: split_idx + 1], left_tan, center_tan, max_error, depth - 1
    )
    right = _fit_recursive(
        pts[split_idx:], -center_tan, right_tan, max_error, depth - 1
    )
    return left + right


def _fit_one_bezier(
    pts: np.ndarray, left_tan: np.ndarray, right_tan: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Solve the least-squares system for two interior control points.

    Standard Schneider derivation: given chord-length parameterization
    ``u_i`` over ``pts``, find the alphas such that the two interior control
    points are ``p0 + alpha_l * left_tan`` and ``p3 + alpha_r * right_tan``.
    Closed-form 2x2 normal equations.
    """
    p0, p3 = pts[0], pts[-1]
    u = _chord_length_params(pts)
    a1 = np.outer(3 * (1 - u) ** 2 * u, left_tan)
    a2 = np.outer(3 * (1 - u) * u ** 2, right_tan)
    bezier_q = (
        ((1 - u) ** 3)[:, None] * p0
        + ((u ** 3))[:, None] * p3
    )
    tmp = pts - bezier_q
    c11 = np.sum(a1 * a1)
    c12 = np.sum(a1 * a2)
    c22 = np.sum(a2 * a2)
    x1 = np.sum(a1 * tmp)
    x2 = np.sum(a2 * tmp)
    det = c11 * c22 - c12 * c12
    if abs(det) < 1e-12:
        # Fall back to a simple 1/3 chord distance for the alphas.
        seg_len = float(np.linalg.norm(p3 - p0))
        alpha_l = alpha_r = seg_len / 3.0
    else:
        alpha_l = (x1 * c22 - x2 * c12) / det
        alpha_r = (c11 * x2 - c12 * x1) / det
    # Reject negative or absurdly large alphas (Schneider's heuristic).
    seg_len = float(np.linalg.norm(p3 - p0))
    if alpha_l < 1e-6 or alpha_r < 1e-6:
        alpha_l = alpha_r = seg_len / 3.0
    if alpha_l > 10.0 * seg_len:
        alpha_l = seg_len / 3.0
    if alpha_r > 10.0 * seg_len:
        alpha_r = seg_len / 3.0
    p1 = p0 + alpha_l * left_tan
    p2 = p3 + alpha_r * right_tan
    return p0, p1, p2, p3


def _chord_length_params(pts: np.ndarray) -> np.ndarray:
    dists = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(dists)])
    total = cum[-1]
    if total < 1e-12:
        return np.linspace(0.0, 1.0, len(pts))
    return cum / total


def _max_error(
    pts: np.ndarray,
    bezier: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> tuple[float, int]:
    """Return ``(max_distance, index_of_worst_point)``."""
    p0, p1, p2, p3 = bezier
    u = _chord_length_params(pts)
    q = (
        ((1 - u) ** 3)[:, None] * p0
        + (3 * (1 - u) ** 2 * u)[:, None] * p1
        + (3 * (1 - u) * u ** 2)[:, None] * p2
        + (u ** 3)[:, None] * p3
    )
    dists = np.linalg.norm(pts - q, axis=1)
    idx = int(np.argmax(dists))
    return float(dists[idx]), idx


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return np.array([1.0, 0.0])
    return v / n


def _fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return f"{x:.3f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Corner-preservation gate (used to validate Approach B's output)
# ---------------------------------------------------------------------------


def _preserves_corners(
    original_svg: str,
    smoothed_svg: str,
    *,
    corner_angle_deg: float = 75.0,
    retention_threshold: float = 0.8,
) -> bool:
    """Approve a smoothed SVG iff it kept enough of the original sharp corners.

    If the original has zero sharp corners (e.g. an all-curves logo like cleo)
    we vacuously accept any smoothing.
    """
    original_corners = _count_sharp_corners(
        original_svg, corner_angle_deg=corner_angle_deg
    )
    if original_corners == 0:
        return True
    smoothed_corners = _count_sharp_corners(
        smoothed_svg, corner_angle_deg=corner_angle_deg
    )
    return smoothed_corners >= int(math.floor(retention_threshold * original_corners))


def _count_sharp_corners(svg: str, *, corner_angle_deg: float = 75.0) -> int:
    """Count vertices with turn angle > threshold across every <path> in svg."""
    try:
        from svgpathtools import parse_path
    except Exception:
        return 0

    total = 0
    for d in re.findall(r'<path[^>]*\bd\s*=\s*["\']([^"\']*)["\']', svg, re.IGNORECASE):
        try:
            path = parse_path(d)
        except Exception:
            continue
        for sub, closed in _split_into_subpaths(path):
            polyline = _sample_polyline(sub, step=0.8)
            if polyline is None or len(polyline) < 3:
                continue
            corners = _find_corners(
                polyline, angle_threshold_deg=corner_angle_deg, closed=closed
            )
            total += len(corners)
    return total
