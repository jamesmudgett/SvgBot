from __future__ import annotations

from app.services.cairo_compat import cairo_available, rasterize_svg_bytes


def rasterize_svg(svg: str, width: int, height: int):
    """Rasterize SVG to RGB PIL image for fidelity metrics."""
    return rasterize_svg_bytes(svg, width, height)


def count_paths(svg: str) -> int:
    import re

    return len(re.findall(r"<(?:[\w-]+:)?path\b", svg, re.IGNORECASE))
