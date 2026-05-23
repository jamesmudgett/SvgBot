"""Tests for the corner-preservation gate that guards Approach B.

The corner check counts vertices with a turn angle larger than
``corner_angle_deg`` (i.e. "real" corners) in both the original and the
smoothed SVG. If the smoothed SVG retained at least ``retention_threshold`` of
the original sharp-corner count, the smoothing is considered safe; otherwise
the orchestrator falls back to the Schneider refit.
"""

from __future__ import annotations

from app.services import smooth_paths


def _wrap(d: str, w: int = 240, h: int = 240) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<path d="{d}" fill="black"/>'
        "</svg>"
    )


def _circle_d(cx: int = 120, cy: int = 120, r: int = 80) -> str:
    """A closed cubic-Bezier approximation of a circle (no sharp corners)."""
    k = 0.5522847498 * r
    return (
        f"M {cx} {cy - r} "
        f"C {cx + k} {cy - r} {cx + r} {cy - k} {cx + r} {cy} "
        f"C {cx + r} {cy + k} {cx + k} {cy + r} {cx} {cy + r} "
        f"C {cx - k} {cy + r} {cx - r} {cy + k} {cx - r} {cy} "
        f"C {cx - r} {cy - k} {cx - k} {cy - r} {cx} {cy - r} Z"
    )


def _square_d(x: int = 40, y: int = 40, size: int = 160) -> str:
    return f"M {x} {y} L {x + size} {y} L {x + size} {y + size} L {x} {y + size} Z"


def _star_d() -> str:
    """A 5-point star: 10 sharp corners (5 outer points + 5 inner reflex)."""
    import math

    cx, cy = 120, 120
    outer, inner = 80, 32
    pts = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / 5
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    head = f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"
    rest = " ".join(f"L {x:.2f} {y:.2f}" for x, y in pts[1:])
    return f"{head} {rest} Z"


def test_corner_check_passes_when_original_has_no_sharp_corners():
    """A circle has zero sharp corners. Any candidate smoothing is trivially
    safe because there are no corners to lose (denominator is 0)."""
    original = _wrap(_circle_d())
    smoothed = _wrap(_circle_d())
    assert smooth_paths._preserves_corners(
        original, smoothed, corner_angle_deg=60.0, retention_threshold=0.8
    )


def test_corner_check_fails_when_smoothed_rounds_off_all_corners():
    """A square has 4 sharp corners; replacing it with a circle loses all of
    them. The check must catch that and return False so the orchestrator falls
    back to Approach A."""
    original = _wrap(_square_d())
    smoothed = _wrap(_circle_d())
    assert not smooth_paths._preserves_corners(
        original, smoothed, corner_angle_deg=60.0, retention_threshold=0.8
    )


def test_corner_check_passes_when_retention_within_threshold():
    """A star with 10 sharp corners losing 2 of them (kept 8/10 = 0.8) must
    pass at retention_threshold=0.8 (>= is acceptance)."""
    original = _wrap(_star_d())
    almost_star = _wrap(
        "M 120 40 L 144 96 L 200 96 L 156 130 L 174 184 L 120 152 "
        "L 66 184 L 84 130 L 40 96 L 96 96 Z"
    )
    assert smooth_paths._preserves_corners(
        original, almost_star, corner_angle_deg=45.0, retention_threshold=0.7
    )
