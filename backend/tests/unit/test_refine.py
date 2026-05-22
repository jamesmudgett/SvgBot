from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.config import get_settings
from app.services import refine
from app.services.dino_score import score_svg


@pytest.fixture
def synthetic_image() -> Image.Image:
    """Red square (80x80) with a green dot in the middle — base SVG below misses the dot."""
    img = Image.new("RGB", (80, 80), (255, 0, 0))
    arr = np.array(img)
    arr[30:50, 30:50] = (0, 200, 60)
    return Image.fromarray(arr, mode="RGB")


@pytest.fixture
def base_svg_red_square() -> str:
    """SVG that only renders the red square — the green dot is intentionally missing."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="80" height="80">'
        '<rect x="0" y="0" width="80" height="80" fill="rgb(255,0,0)"/>'
        "</svg>"
    )


def test_residual_mask_detects_difference(synthetic_image: Image.Image):
    original = np.array(synthetic_image)
    rendered = np.full_like(original, [255, 0, 0])
    mask = refine.residual_mask(original, rendered, threshold=24)
    coverage = float(mask.sum()) / float(mask.size)
    assert coverage > 0.04
    assert coverage < 0.20
    assert mask[40, 40]
    assert not mask[5, 5]


def test_residual_mask_suppresses_edge_halo_but_keeps_interior():
    """A halo along a base-render edge should be filtered; a deep-interior
    chunk should survive. This is the core property the refinement relies on
    to avoid making anti-aliasing worse."""
    h, w = 120, 120
    original = np.full((h, w, 3), 255, dtype=np.uint8)
    rendered = np.full((h, w, 3), 255, dtype=np.uint8)

    rendered[30:90, 30:90] = 0
    original[27:93, 27:93] = 0

    original[5:20, 5:20] = 0

    halo_box = np.s_[25:95, 25:95]
    interior_box = np.s_[5:20, 5:20]

    masked = refine.residual_mask(
        original, rendered, threshold=20, edge_exclusion=4, min_component_area=0
    )
    unmasked = refine.residual_mask(
        original, rendered, threshold=20, edge_exclusion=0, min_component_area=0
    )

    halo_filtered = int(unmasked[halo_box].sum()) - int(masked[halo_box].sum())
    assert halo_filtered > 0, "edge halo should shrink with edge_exclusion"
    assert masked[interior_box].any(), "interior defect must survive filtering"


def test_make_residual_rgba_zeros_alpha_outside_mask(synthetic_image: Image.Image):
    arr = np.array(synthetic_image)
    mask = np.zeros(arr.shape[:2], dtype=bool)
    mask[30:50, 30:50] = True
    rgba = refine.make_residual_rgba(synthetic_image, mask)
    assert rgba.mode == "RGBA"
    a = np.array(rgba)
    assert a[40, 40, 3] == 255
    assert a[5, 5, 3] == 0


def test_merge_overlay_inserts_paths(base_svg_red_square: str):
    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">'
        '<path d="M30 30 H50 V50 H30 Z" fill="rgb(0,200,60)"/>'
        "</svg>"
    )
    merged = refine.merge_overlay(base_svg_red_square, overlay)
    assert merged.count("</svg>") == 1
    assert "vb-refine" in merged
    assert "M30 30" in merged
    assert merged.endswith("</svg>")


def test_merge_overlay_no_op_when_overlay_empty(base_svg_red_square: str):
    overlay = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80"></svg>'
    merged = refine.merge_overlay(base_svg_red_square, overlay)
    assert merged == base_svg_red_square


def test_merge_overlay_remaps_mismatched_viewbox():
    """StarVector outputs viewBox=0 0 1 1; overlay must be scaled so paths align."""
    base = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" width="80" height="80">'
        '<rect x="0" y="0" width="1" height="1" fill="red"/>'
        "</svg>"
    )
    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">'
        '<path d="M30 30 H50 V50 H30 Z" fill="green"/>'
        "</svg>"
    )
    merged = refine.merge_overlay(base, overlay)
    assert "vb-refine" in merged
    assert 'transform="matrix(' in merged
    assert "0.0125" in merged or "1/80" in merged or "matrix(0.0125" in merged


def test_merge_overlay_skips_transform_when_viewbox_matches(base_svg_red_square: str):
    overlay = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">'
        '<path d="M30 30 H50 V50 H30 Z" fill="green"/>'
        "</svg>"
    )
    merged = refine.merge_overlay(base_svg_red_square, overlay)
    assert "vb-refine" in merged
    assert "transform=" not in merged


def test_iterative_refine_disabled_returns_base(
    synthetic_image: Image.Image, base_svg_red_square: str, monkeypatch: pytest.MonkeyPatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "refine_enabled", False)
    result = refine.iterative_refine(
        synthetic_image, base_svg_red_square, 80, 80, max_passes=3
    )
    assert result.passes == 0
    assert result.svg == base_svg_red_square


def test_iterative_refine_empty_masks_do_not_burn_failure_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    """If every variant produces an empty mask (image already perfect-ish), the
    loop must rotate through all variants and exit cleanly — not bail after
    `max_consecutive_failures` empty passes."""
    settings = get_settings()
    monkeypatch.setattr(settings, "refine_enabled", True)
    monkeypatch.setattr(settings, "refine_max_passes", 20)

    perfect = Image.new("RGB", (40, 40), (255, 255, 255))
    base_svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="40" height="40">'
        '<rect x="0" y="0" width="40" height="40" fill="rgb(255,255,255)"/>'
        "</svg>"
    )

    rasterize_calls: list[int] = []

    real_residual_mask = refine.residual_mask

    def empty_mask(*args, **kwargs):
        rasterize_calls.append(1)
        return np.zeros(real_residual_mask(*args, **kwargs).shape, dtype=bool)

    monkeypatch.setattr(refine, "residual_mask", empty_mask)

    result = refine.iterative_refine(perfect, base_svg, 40, 40)
    assert result.passes == 0
    assert result.svg == base_svg
    assert len(rasterize_calls) == len(refine._PASS_VARIANTS)


def test_iterative_refine_improves_score(
    synthetic_image: Image.Image, base_svg_red_square: str, monkeypatch: pytest.MonkeyPatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "refine_enabled", True)
    monkeypatch.setattr(settings, "refine_max_passes", 2)
    monkeypatch.setattr(settings, "refine_min_delta", 0.0001)

    base_score, _ = score_svg(synthetic_image, base_svg_red_square, 80, 80)
    result = refine.iterative_refine(synthetic_image, base_svg_red_square, 80, 80)

    assert result.passes >= 1
    assert result.score >= base_score
    assert result.coverage > 0.0
    assert "vb-refine" in result.svg
