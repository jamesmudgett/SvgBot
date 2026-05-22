from app.services import vtracer_engine
from app.services.fontless import is_fontless
from app.services.orchestrator import vectorize_bytes


def test_vectorize_logo(logo_png: bytes):
    out = vectorize_bytes(logo_png, quality="standard", engine="vtracer", fontless=True)
    assert out.svg.strip().startswith("<")
    assert "svg" in out.svg.lower()
    assert is_fontless(out.svg)
    assert out.path_count >= 1
    assert out.dino_score >= 0


def test_vectorize_logo_smooth_engine(logo_png: bytes):
    """The smooth-curve pipeline should produce a usable SVG even on a
    synthetic logo. We don't assert path-count strictly less than the default
    path because synthetic 2-color images already trace minimally — instead
    we just lock in that the engine wires up end-to-end and stays fontless."""
    out = vectorize_bytes(
        logo_png, quality="standard", engine="vtracer_smooth", fontless=True
    )
    assert out.engine == "vtracer_smooth"
    assert out.svg.strip().startswith("<")
    assert is_fontless(out.svg)
    assert out.path_count >= 1
    assert out.dino_score >= 0


def test_logo_smooth_grid_uses_smooth_curve_params():
    """Sanity-check: every smooth-grid entry actually opts into smoother curves
    (corner_threshold >= 75 OR length_threshold >= 5.5)."""
    for params in vtracer_engine.LOGO_SMOOTH_GRID:
        smooth = (
            params.get("corner_threshold", 60) >= 75
            or params.get("length_threshold", 4.0) >= 5.5
        )
        assert smooth, f"smooth grid entry not actually smooth: {params}"
