"""SVG rasterization without native Cairo (Windows-friendly)."""

from __future__ import annotations

import sys
from io import BytesIO
from types import ModuleType

from PIL import Image

_patched = False
_stubs_installed = False


def cairo_available() -> bool:
    if "cairosvg" in sys.modules and getattr(sys.modules["cairosvg"], "_vectorbot_stub", False):
        return False
    try:
        import cairocffi

        cairocffi.cairo  # noqa: B018
        import cairosvg  # noqa: F401

        return True
    except Exception:
        return False


def rasterize_svg_bytes(svg: str, width: int, height: int) -> Image.Image:
    """Rasterize SVG to RGB PIL; uses Cairo when present, else svglib/reportlab."""
    if cairo_available():
        try:
            import cairosvg

            png_bytes = cairosvg.svg2png(
                bytestring=svg.encode("utf-8"),
                output_width=width,
                output_height=height,
                background_color="white",
            )
            return Image.open(BytesIO(png_bytes)).convert("RGB")
        except Exception:
            pass

    return _rasterize_svg_via_pdf(svg, width, height)


def _rasterize_svg_via_pdf(svg: str, width: int, height: int) -> Image.Image:
    """svglib → PDF → pixmap (no native Cairo required)."""
    from reportlab.graphics import renderPDF
    from svglib.svglib import svg2rlg

    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(
            "SVG rasterization requires PyMuPDF on Windows: pip install pymupdf"
        ) from e

    drawing = svg2rlg(BytesIO(svg.encode("utf-8")))
    if drawing is None:
        raise ValueError("Could not parse SVG for rasterization")

    pdf_bytes = renderPDF.drawToString(drawing)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[0]
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError("Empty SVG bounds")
        matrix = fitz.Matrix(width / rect.width, height / rect.height)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def clean_svg_without_cairo(svg_text: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(svg_text, "xml")
    cleaned = soup.prettify()
    return "\n".join(
        line for line in cleaned.split("\n") if not line.strip().startswith("<?xml")
    )


def rasterize_svg_starvector(
    svg_string: str,
    resolution: int = 224,
    dpi: int = 128,
    scale: int = 2,
) -> Image.Image:
    _ = dpi, scale
    try:
        return rasterize_svg_bytes(svg_string, resolution, resolution)
    except Exception:
        return Image.new("RGB", (resolution, resolution), color="white")


def _remove_broken_cairo_modules() -> None:
    """Drop failed cairosvg/cairocffi imports so stubs can be installed."""
    for name in ("cairosvg", "cairocffi", "cairosvg.surface", "cairosvg.url"):
        sys.modules.pop(name, None)


def ensure_cairo_stubs() -> None:
    """Install cairosvg/cairocffi stubs so starvector.data.util can import on Windows."""
    global _stubs_installed
    if _stubs_installed:
        return
    if cairo_available():
        _stubs_installed = True
        return

    existing = sys.modules.get("cairosvg")
    if existing is not None and getattr(existing, "_vectorbot_stub", False):
        _stubs_installed = True
        return

    # Broken real cairosvg may already be in sys.modules — replace it with our stub.
    _remove_broken_cairo_modules()

    cairocffi = ModuleType("cairocffi")
    sys.modules["cairocffi"] = cairocffi

    cairosvg = ModuleType("cairosvg")
    cairosvg._vectorbot_stub = True  # type: ignore[attr-defined]

    def svg2png(bytestring=None, write_to=None, **kwargs):
        svg = (bytestring or b"").decode("utf-8", errors="replace")
        w = int(kwargs.get("output_width") or 256)
        h = int(kwargs.get("output_height") or 256)
        png = BytesIO()
        rasterize_svg_bytes(svg, w, h).save(png, format="PNG")
        data = png.getvalue()
        if write_to is not None:
            write_to.write(data)
            return None
        return data

    def svg2svg(bytestring=None, **kwargs):
        _ = kwargs
        if isinstance(bytestring, bytes):
            return bytestring
        return (bytestring or "").encode("utf-8")

    cairosvg.svg2png = svg2png
    cairosvg.svg2svg = svg2svg
    sys.modules["cairosvg"] = cairosvg
    _stubs_installed = True


def apply_starvector_patches() -> None:
    """Patch starvector.data.util rasterize/clean helpers."""
    global _patched
    ensure_cairo_stubs()
    if _patched:
        return

    import starvector.data.util as sv_util
    from svgpathtools import svgstr2paths

    def patched_clean_svg(svg_text, output_width=None, output_height=None):
        _ = output_width, output_height
        if cairo_available():
            try:
                return _original_clean_svg(svg_text, output_width, output_height)
            except Exception:
                pass
        try:
            cleaned = clean_svg_without_cairo(svg_text)
            svgstr2paths(cleaned)
            return cleaned
        except Exception:
            return svg_text

    def patched_process_and_rasterize_svg(svg_string, resolution=256, dpi=128, scale=2):
        try:
            svgstr2paths(svg_string)
            out_svg = svg_string
        except Exception:
            try:
                out_svg = patched_clean_svg(svg_string)
                svgstr2paths(out_svg)
            except Exception:
                out_svg = sv_util.use_placeholder()
        raster_image = rasterize_svg_starvector(out_svg, resolution, dpi, scale)
        return out_svg, raster_image

    _original_clean_svg = sv_util.clean_svg
    sv_util.rasterize_svg = rasterize_svg_starvector
    sv_util.clean_svg = patched_clean_svg
    sv_util.process_and_rasterize_svg = patched_process_and_rasterize_svg
    _patched = True
