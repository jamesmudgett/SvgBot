from __future__ import annotations

import tempfile
from pathlib import Path

import vtracer
from PIL import Image

from app.services.dino_score import score_svg


def _write_temp_png(img: Image.Image) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(f.name, format="PNG")
    return Path(f.name)


DEFAULT_GRID = [
    {"colormode": "color", "color_precision": 6, "filter_speckle": 4, "path_precision": 6},
    {"colormode": "color", "color_precision": 4, "filter_speckle": 2, "path_precision": 7},
    {"colormode": "color", "color_precision": 8, "filter_speckle": 4, "path_precision": 5},
    {"colormode": "binary", "color_precision": 4, "filter_speckle": 2, "path_precision": 6},
]

# Logos with text + flat fills (e.g. brand marks) — color mode, sharper paths
LOGO_GRID = [
    {
        "colormode": "color",
        "color_precision": 6,
        "filter_speckle": 2,
        "path_precision": 7,
        "corner_threshold": 70,
        "length_threshold": 3.5,
        "layer_difference": 12,
    },
    {
        "colormode": "color",
        "color_precision": 4,
        "filter_speckle": 2,
        "path_precision": 8,
        "corner_threshold": 60,
        "length_threshold": 3.5,
    },
    {
        "colormode": "color",
        "color_precision": 8,
        "filter_speckle": 4,
        "path_precision": 6,
        "layer_difference": 8,
    },
    {"colormode": "binary", "color_precision": 4, "filter_speckle": 2, "path_precision": 7},
]


# Smooth-curve grid for logos: bigger filter_speckle drops noise paths,
# higher corner_threshold + longer length_threshold collapse short straight
# segments into curves, lower path_precision rounds away sub-pixel jitter.
# Pair with a palette-quantized input (preprocess.clean_for_tracing) so the
# tracer doesn't waste detail chasing JPEG/AA noise.
LOGO_MONO_GRID = [
    {
        "colormode": "binary",
        "mode": "spline",
        "filter_speckle": 4,
        "path_precision": 7,
        "corner_threshold": 75,
        "length_threshold": 5.0,
        "splice_threshold": 60,
    },
    {
        "colormode": "binary",
        "mode": "spline",
        "filter_speckle": 6,
        "path_precision": 6,
        "corner_threshold": 85,
        "length_threshold": 6.5,
        "splice_threshold": 70,
    },
    {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "color_precision": 2,
        "filter_speckle": 6,
        "path_precision": 6,
        "corner_threshold": 80,
        "length_threshold": 5.5,
    },
]


LOGO_SMOOTH_GRID = [
    {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "color_precision": 5,
        "filter_speckle": 6,
        "path_precision": 5,
        "corner_threshold": 80,
        "length_threshold": 6.0,
        "splice_threshold": 65,
        "layer_difference": 16,
    },
    {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "color_precision": 4,
        "filter_speckle": 8,
        "path_precision": 4,
        "corner_threshold": 90,
        "length_threshold": 8.0,
        "splice_threshold": 75,
    },
    {
        "colormode": "color",
        "hierarchical": "cutout",
        "mode": "spline",
        "color_precision": 5,
        "filter_speckle": 6,
        "path_precision": 5,
        "corner_threshold": 75,
        "length_threshold": 5.5,
        "splice_threshold": 60,
    },
    {
        "colormode": "binary",
        "mode": "spline",
        "filter_speckle": 6,
        "path_precision": 5,
        "corner_threshold": 85,
        "length_threshold": 7.0,
        "splice_threshold": 70,
    },
]


def vectorize(img: Image.Image, **params) -> str:
    inp = _write_temp_png(img)
    out = inp.with_suffix(".svg")
    opts = {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "filter_speckle": 4,
        "color_precision": 6,
        "path_precision": 6,
    }
    opts.update(params)
    try:
        vtracer.convert_image_to_svg_py(str(inp), str(out), **opts)
        return out.read_text(encoding="utf-8")
    finally:
        inp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def auto_tune(
    img: Image.Image,
    width: int,
    height: int,
    grid: list[dict] | None = None,
) -> tuple[str, float]:
    if grid is None:
        grid = DEFAULT_GRID

    best_svg = ""
    best_score = -1.0
    for params in grid:
        try:
            svg = vectorize(img, **params)
            dino, _ = score_svg(img, svg, width, height)
            if dino > best_score:
                best_score = dino
                best_svg = svg
        except Exception:
            continue

    if not best_svg:
        best_svg = vectorize(img)
        best_score, _ = score_svg(img, best_svg, width, height)
    return best_svg, best_score
