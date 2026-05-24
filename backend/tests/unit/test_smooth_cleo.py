"""Cleo regression guard for the geometric smoothing pass.

The cleo logo is the canonical "choppy text edge" failure mode: after the
vtracer_mono pipeline quantizes to 2 colors and traces, the pill outline and
letter contours come out as stair-stepped polylines. The hybrid smoothing pass
must turn that into smooth curves without dropping the DinoScore, and on cleo
specifically the supersample-retrace path (Approach B) should win because the
logo has no sharp corners to lose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import orchestrator, smooth_paths
from app.services.dino_score import score_svg
from app.services.preprocess import load_image_bytes

CLEO_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "cleo.png"


def _count_lines_and_curves(svg: str) -> tuple[int, int]:
    """Return ``(line_commands, curve_commands)`` across every <path d> in svg.

    L/H/V are stair-step line segments; C/S/Q/T are smooth curves. The cleo
    regression is specifically that vtracer_mono emits lots of L commands
    along letter contours; a successful smoothing pass should swing the ratio
    toward curves.
    """
    lines = 0
    curves = 0
    for d in re.findall(r'<path[^>]*\bd\s*=\s*["\']([^"\']*)["\']', svg, re.IGNORECASE):
        lines += len(re.findall(r"[LlHhVv]", d))
        curves += len(re.findall(r"[CcSsQqTt]", d))
    return lines, curves


@pytest.mark.skipif(not CLEO_PATH.is_file(), reason="cleo fixture missing")
def test_cleo_hybrid_smoothing_swaps_lines_for_curves_and_preserves_score():
    """End-to-end cleo regression guard.

    - Run vtracer_mono on the cleo fixture to get the pre-smoothing SVG.
    - Apply the hybrid smoothing pass with logo-tier parameters.
    - Assert the smoothed SVG is dominated by curve commands (the choppy
      input is dominated by line commands).
    - Assert DinoScore stays within ``path_smoothing_max_delta``.
    - Assert ``smoothing_method == 'supersample'`` (B is expected to win on
      cleo because it has no sharp corners to lose).
    """
    data = CLEO_PATH.read_bytes()

    settings = get_settings()
    # Run vtracer_mono with smoothing disabled so we have a clean baseline.
    original_enabled = settings.path_smoothing_enabled
    settings.path_smoothing_enabled = False
    try:
        base_out = orchestrator.vectorize_bytes(
            data, quality="standard", engine="vtracer_mono", fontless=False
        )
    finally:
        settings.path_smoothing_enabled = original_enabled

    base_svg = base_out.svg
    base_dino = base_out.dino_score
    img, _ = load_image_bytes(data, settings.max_image_dimension)
    width, height = img.size

    def score_fn(candidate_svg: str) -> float:
        dino, _ = score_svg(img, candidate_svg, width, height)
        return dino

    smoothed_svg, method, delta = smooth_paths.smooth_svg(
        base_svg,
        width,
        height,
        kind="logo",
        score_fn=score_fn,
        settings=settings,
        source_image=img,
    )

    base_lines, base_curves = _count_lines_and_curves(base_svg)
    smoothed_lines, smoothed_curves = _count_lines_and_curves(smoothed_svg)

    assert method != "none", (
        f"cleo logo must accept at least one smoothing method "
        f"(base_dino={base_dino:.4f}, delta={delta:+.4f})"
    )
    assert method == "supersample", (
        f"cleo has no sharp corners; Approach B (supersample) should win, "
        f"but smooth_svg returned method={method!r}"
    )
    assert smoothed_curves > smoothed_lines, (
        f"smoothed cleo SVG must be dominated by curve commands "
        f"(curves={smoothed_curves}, lines={smoothed_lines})"
    )
    assert smoothed_curves >= base_curves, (
        f"smoothed cleo SVG must have at least as many curves as the choppy "
        f"baseline (base_curves={base_curves}, smoothed_curves={smoothed_curves})"
    )

    new_dino = score_fn(smoothed_svg)
    assert new_dino >= base_dino - settings.path_smoothing_max_delta_logo, (
        f"smoothing must not drop DinoScore below the logo gate "
        f"(base={base_dino:.4f}, smoothed={new_dino:.4f}, "
        f"delta={new_dino - base_dino:+.4f}, gate={settings.path_smoothing_max_delta_logo})"
    )
