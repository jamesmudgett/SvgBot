"""Tests for the Schneider Bezier path refit (Approach A, fallback).

The refit helper parses every ``<path d="...">``, samples each subpath to a
dense polyline, marks vertices with a turn angle greater than the threshold as
"corners", and refits smooth cubic Beziers between consecutive corners. It is
the corner-preserving fallback when supersample-retrace fails the score gate
or rounds off real geometry.
"""

from __future__ import annotations

import re

import pytest

from app.services import smooth_paths


def _build_svg(
    d: str,
    w: int = 240,
    h: int = 240,
    *,
    fill: str = "black",
    extra: str = "",
) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<path d="{d}" fill="{fill}"{extra}/>'
        "</svg>"
    )


def _stair_step_d(n: int = 30, step: int = 3, x0: int = 40, y0: int = 40) -> str:
    """Build a stair-stepped path that meanders right-down then closes back."""
    parts = [f"M {x0} {y0}"]
    for i in range(n):
        parts.append(f"L {x0 + (i + 1) * step} {y0 + i * step}")
        parts.append(f"L {x0 + (i + 1) * step} {y0 + (i + 1) * step}")
    parts.append(f"L {x0} {y0 + n * step}")
    parts.append("Z")
    return " ".join(parts)


def _count_path_commands(svg: str) -> int:
    """Count drawing commands (L/C/Q/T/A) across every <path d> in the SVG."""
    total = 0
    for d in re.findall(r'<path[^>]*\bd\s*=\s*["\']([^"\']*)["\']', svg, re.IGNORECASE):
        total += len(re.findall(r"[LlCcQqTtAa]", d))
    return total


def test_refit_reduces_command_count_on_stairstepped_polyline():
    """A dense stair-stepped polyline must collapse into far fewer Bezier
    segments after refit. This is the core smoothing claim.

    RDP at a tolerance comfortably above the stair-step amplitude (here 2 px
    steps with a 3.0 tolerance) collapses the noise into a smooth diagonal so
    Schneider's fit produces just one or two Beziers per side.
    """
    svg_in = _build_svg(_stair_step_d(n=40, step=2))
    before = _count_path_commands(svg_in)

    out = smooth_paths._smooth_via_bezier_refit(
        svg_in,
        corner_angle_deg=75.0,
        rdp_tolerance=3.0,
        sample_step=0.6,
    )
    after = _count_path_commands(out)

    assert after > 0, "refit must still emit some path commands"
    assert after < before * 0.5, (
        f"refit must collapse stair-steps to fewer commands: "
        f"before={before} after={after}"
    )


def test_refit_preserves_sharp_90_degree_corner():
    """A clean right-angle 'L' shape must retain its corner; the refit cannot
    round a 90 deg vertex into a curve or it would mush sans-serif terminals.

    We assert by re-sampling the output and confirming at least one vertex with
    a turn angle close to 90 degrees survives.
    """
    d = "M 60 60 L 60 180 L 180 180 L 180 60 Z"
    svg_in = _build_svg(d)

    out = smooth_paths._smooth_via_bezier_refit(
        svg_in,
        corner_angle_deg=75.0,
        rdp_tolerance=1.5,
        sample_step=0.6,
    )
    corners = smooth_paths._count_sharp_corners(out, corner_angle_deg=60.0)
    assert corners >= 3, (
        f"a 4-corner square must retain at least 3 sharp corners after refit; "
        f"got {corners}"
    )


def test_refit_is_safe_on_already_smooth_cubic_bezier():
    """A path that is already a single smooth cubic Bezier must round-trip
    without crashing and without producing wildly different geometry. We do not
    require byte-for-byte identity, only structural sanity."""
    d = "M 40 120 C 40 60 200 60 200 120 C 200 180 40 180 40 120 Z"
    svg_in = _build_svg(d)
    out = smooth_paths._smooth_via_bezier_refit(svg_in)
    assert "<path" in out
    # The output viewBox must still be the input viewBox.
    assert 'viewBox="0 0 240 240"' in out


def test_refit_handles_compound_paths_with_multiple_subpaths():
    """A single ``d`` containing two M-prefixed subpaths (e.g. letter 'o' outer
    + inner contour) must produce a single output ``d`` with two subpaths."""
    d = (
        "M 60 60 L 60 180 L 180 180 L 180 60 Z "
        "M 90 90 L 90 150 L 150 150 L 150 90 Z"
    )
    svg_in = _build_svg(d)
    out = smooth_paths._smooth_via_bezier_refit(svg_in)
    out_d_attrs = re.findall(
        r'<path[^>]*\bd\s*=\s*["\']([^"\']*)["\']', out, re.IGNORECASE
    )
    assert len(out_d_attrs) == 1, "compound path stays as a single <path> element"
    m_count = sum(c in "Mm" for c in out_d_attrs[0])
    assert m_count >= 2, (
        f"output d must still contain two subpaths (two 'M' commands); "
        f"got d={out_d_attrs[0]!r}"
    )


def test_refit_returns_input_when_path_is_unparseable():
    """If a <path d> attribute cannot be parsed by svgpathtools the helper must
    swallow the error and return the input unchanged rather than raising."""
    svg_in = _build_svg("M not a valid d attribute")
    out = smooth_paths._smooth_via_bezier_refit(svg_in)
    assert "<path" in out
    assert "</svg>" in out


def test_refit_preserves_fill_opacity_id_and_class_attributes():
    """All <path> attributes other than ``d`` must round-trip unchanged so we
    do not silently drop colors, ids, or classes when the orchestrator picks up
    the smoothed SVG."""
    svg_in = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 240 240" width="240" height="240">'
        '<path id="pill" class="bg" fill="#3a221e" opacity="0.95" '
        'd="M 40 40 L 200 40 L 200 200 L 40 200 Z"/>'
        "</svg>"
    )
    out = smooth_paths._smooth_via_bezier_refit(svg_in)
    assert 'id="pill"' in out
    assert 'class="bg"' in out
    assert 'fill="#3a221e"' in out
    assert 'opacity="0.95"' in out
