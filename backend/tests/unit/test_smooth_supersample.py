"""Tests for the supersample-retrace path smoothing helper (Approach B).

The supersample helper rasterizes the input SVG at scale * (w, h), optionally
applies a small Gaussian blur to damp pixel-step ramps in the rendered AA, then
re-traces with VTracer. The output viewBox must match the original input
dimensions even though tracing happened at a higher resolution.
"""

from __future__ import annotations

import re

from app.services import smooth_paths


def _build_svg(d: str, w: int, h: int, fill: str = "black") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<path d="{d}" fill="{fill}"/>'
        "</svg>"
    )


def _extract_viewbox(svg: str) -> tuple[float, float, float, float] | None:
    match = re.search(r'viewBox\s*=\s*["\']([^"\']+)["\']', svg, re.IGNORECASE)
    if not match:
        return None
    parts = match.group(1).split()
    if len(parts) != 4:
        return None
    return tuple(float(p) for p in parts)  # type: ignore[return-value]


def test_supersample_returns_valid_svg_with_paths():
    """End-to-end smoke test: the helper must produce a parseable SVG with at
    least one ``<path>`` element."""
    svg_in = _build_svg("M 20 20 L 100 20 L 100 100 L 20 100 Z", 240, 240)
    out = smooth_paths._smooth_via_supersample(
        svg_in, 240, 240, scale=2, blur_sigma=0.5
    )
    assert "<svg" in out
    assert "<path" in out
    assert "</svg>" in out


def test_supersample_renormalizes_viewbox_to_original():
    """Output viewBox must equal the input dimensions even though VTracer traced
    a 4x raster. Downstream consumers (rasterize_svg, refine, sanitize) assume
    the viewBox matches the source image dimensions."""
    svg_in = _build_svg("M 40 40 L 200 40 L 200 200 L 40 200 Z", 240, 240)
    out = smooth_paths._smooth_via_supersample(
        svg_in, 240, 240, scale=4, blur_sigma=0.5
    )
    vb = _extract_viewbox(out)
    assert vb is not None, "output SVG must have a viewBox attribute"
    assert vb[2] == 240, f"viewBox width must be 240 (got {vb[2]})"
    assert vb[3] == 240, f"viewBox height must be 240 (got {vb[3]})"


def test_supersample_handles_blur_zero():
    """blur_sigma=0 path must not raise (cv2.GaussianBlur with sigma=0 derives
    sigma from ksize, so we guard against that path internally)."""
    svg_in = _build_svg("M 20 20 L 80 20 L 80 80 L 20 80 Z", 100, 100)
    out = smooth_paths._smooth_via_supersample(
        svg_in, 100, 100, scale=2, blur_sigma=0.0
    )
    assert "<svg" in out
    assert "<path" in out


def test_supersample_clamps_scale_when_input_too_large():
    """Already-large inputs must not blow up memory at scale=4. We clamp the
    effective scale so the supersample raster never exceeds max_dimension."""
    svg_in = _build_svg(
        "M 100 100 L 1500 100 L 1500 1500 L 100 1500 Z", 2000, 2000
    )
    out = smooth_paths._smooth_via_supersample(
        svg_in, 2000, 2000, scale=4, blur_sigma=0.5, max_dimension=2048
    )
    assert "<svg" in out
    vb = _extract_viewbox(out)
    assert vb is not None
    assert vb[2] == 2000
    assert vb[3] == 2000
