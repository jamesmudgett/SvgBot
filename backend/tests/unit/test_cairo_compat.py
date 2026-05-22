from app.services.cairo_compat import clean_svg_without_cairo, rasterize_svg_bytes


def test_rasterize_simple_svg():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
        '<rect x="0" y="0" width="64" height="64" fill="red"/>'
        "</svg>"
    )
    img = rasterize_svg_bytes(svg, 64, 64)
    assert img.size == (64, 64)
    assert img.mode == "RGB"


def test_clean_svg_without_cairo():
    svg = "<svg><circle cx='32' cy='32' r='16'/></svg>"
    out = clean_svg_without_cairo(svg)
    assert "circle" in out.lower()
