"""Tests for the diagnostic CLI at ``backend/scripts/debug_image.py``.

GPU-only paths (StarVector model load + generation) are mocked so the script can
be exercised in CI without CUDA. The visual-inspection PNGs / SVGs are still
written through the real rasterizer.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "backend" / "scripts" / "debug_image.py"


def _load_debug_image_module():
    spec = importlib.util.spec_from_file_location("debug_image_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, "debug_image.py must exist"
    module = importlib.util.module_from_spec(spec)
    sys.modules["debug_image_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def debug_image():
    return _load_debug_image_module()


def test_parse_engines_default_excludes_starvector(debug_image):
    """By default --engines should be a subset that runs without GPU."""
    parsed = debug_image.parse_args(["--image", "x.png", "--output-dir", "out"])
    assert "starvector" not in parsed.engines, (
        "starvector requires a GPU; opt-in only via --engines"
    )
    assert any(e in parsed.engines for e in ("vtracer", "vtracer_smooth"))


def test_parse_engines_starvector_is_opt_in(debug_image):
    parsed = debug_image.parse_args(
        ["--image", "x.png", "--output-dir", "out", "--engines", "starvector"]
    )
    assert parsed.engines == ("starvector",)


def test_parse_engines_rejects_unknown(debug_image):
    with pytest.raises(SystemExit):
        debug_image.parse_args(
            ["--image", "x.png", "--output-dir", "out", "--engines", "midjourney"]
        )


def test_run_writes_outputs_for_vtracer(
    debug_image, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """End-to-end: vtracer pipeline produces SVG + render PNG + a summary row.

    We use a tiny synthetic logo (a red square on white) so vtracer runs in well
    under a second on CPU. Refinement is disabled so the test never touches the
    GPU score path.
    """
    img = Image.new("RGB", (32, 32), (255, 255, 255))
    for x in range(8, 24):
        for y in range(8, 24):
            img.putpixel((x, y), (200, 60, 50))
    image_path = tmp_path / "synthetic.png"
    img.save(image_path)

    out_dir = tmp_path / "out"

    summaries = debug_image.run(
        image_path=image_path,
        output_dir=out_dir,
        engines=("vtracer",),
        starvector_k=1,
        refine=False,
    )

    assert len(summaries) == 1
    row = summaries[0]
    assert row.engine == "vtracer"
    assert row.svg_path.is_file()
    assert row.render_path.is_file()
    assert row.svg_path.suffix == ".svg"
    assert row.render_path.suffix == ".png"
    assert row.dino_score > 0.0


def test_run_with_refine_records_pass_count(
    debug_image, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    img = Image.new("RGB", (40, 40), (255, 255, 255))
    for x in range(10, 30):
        for y in range(10, 30):
            img.putpixel((x, y), (30, 30, 30))
    image_path = tmp_path / "synthetic.png"
    img.save(image_path)

    summaries = debug_image.run(
        image_path=image_path,
        output_dir=tmp_path / "out",
        engines=("vtracer",),
        starvector_k=1,
        refine=True,
    )

    assert summaries[0].refine_passes >= 0
    assert summaries[0].render_path.is_file()


def test_format_summary_table_includes_each_engine(debug_image, tmp_path: Path):
    rows = [
        debug_image.EngineSummary(
            engine="vtracer",
            dino_score=0.81,
            lpips=0.74,
            path_count=12,
            refine_passes=2,
            ms=130,
            svg_path=tmp_path / "vtracer.svg",
            render_path=tmp_path / "vtracer.png",
            candidate_scores=[],
        ),
        debug_image.EngineSummary(
            engine="vtracer_smooth",
            dino_score=0.84,
            lpips=0.79,
            path_count=8,
            refine_passes=1,
            ms=210,
            svg_path=tmp_path / "vtracer_smooth.svg",
            render_path=tmp_path / "vtracer_smooth.png",
            candidate_scores=[],
        ),
    ]
    table = debug_image.format_summary_table(rows)
    assert "vtracer" in table
    assert "vtracer_smooth" in table
    assert "0.84" in table


def test_format_summary_table_shows_candidate_scores_for_starvector(
    debug_image, tmp_path: Path
):
    row = debug_image.EngineSummary(
        engine="starvector",
        dino_score=0.948,
        lpips=0.97,
        path_count=3,
        refine_passes=0,
        ms=40123,
        svg_path=tmp_path / "starvector.svg",
        render_path=tmp_path / "starvector.png",
        candidate_scores=[(0.951, 0.88), (0.948, 0.97), (0.940, 0.90)],
    )
    table = debug_image.format_summary_table([row])
    assert "candidate" in table.lower() or "cand" in table.lower()
    assert "0.951" in table
    assert "0.97" in table


def test_run_skips_starvector_when_unavailable(
    debug_image, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If StarVector raises Unavailable, the runner records a skip row instead of crashing.

    The script invokes ``_load_model()`` itself (so it can capture per-candidate
    scores in the summary), so the test must monkeypatch the loader, not the
    higher-level ``vectorize()`` entrypoint.
    """
    img = Image.new("RGB", (20, 20), (255, 255, 255))
    image_path = tmp_path / "tiny.png"
    img.save(image_path)

    from app.services import starvector_engine

    def fake_load_model():
        raise starvector_engine.StarVectorUnavailable("no GPU in test env")

    monkeypatch.setattr(starvector_engine, "_load_model", fake_load_model)

    summaries = debug_image.run(
        image_path=image_path,
        output_dir=tmp_path / "out",
        engines=("starvector",),
        starvector_k=2,
        refine=False,
    )

    assert len(summaries) == 1
    assert summaries[0].engine == "starvector"
    assert summaries[0].skipped is True
    assert "no GPU" in (summaries[0].skip_reason or "")


def test_run_starvector_records_each_candidate_score(
    debug_image, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When StarVector runs, the summary row must list per-candidate (dino, lpips).

    This is the diagnostic value of the script: it tells the user exactly which
    of the k stochastic generations had the best LPIPS (= crispest letterforms)
    versus which won on raw DinoScore. Without this, "the cleo logo looks subtly
    off" stays a guess.
    """
    img = Image.new("RGB", (256, 256), (255, 255, 255))
    image_path = tmp_path / "tiny.png"
    img.save(image_path)

    from app.services import starvector_engine

    fake_svgs = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" id="a"/>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" id="b"/>',
    ]
    fake_scores = {
        fake_svgs[0]: (0.92, 0.85),
        fake_svgs[1]: (0.91, 0.94),
    }
    call_idx = {"i": 0}

    def fake_load_model():
        return object()

    def fake_generate_one(_model, _img, max_length):
        _ = max_length
        svg = fake_svgs[call_idx["i"]]
        call_idx["i"] += 1
        return svg

    def fake_score_svg(_img, svg, _w, _h):
        return fake_scores[svg]

    monkeypatch.setattr(starvector_engine, "_load_model", fake_load_model)
    monkeypatch.setattr(starvector_engine, "_generate_one", fake_generate_one)
    monkeypatch.setattr(starvector_engine, "score_svg", fake_score_svg)

    summaries = debug_image.run(
        image_path=image_path,
        output_dir=tmp_path / "out",
        engines=("starvector",),
        starvector_k=2,
        refine=False,
    )

    assert len(summaries) == 1
    row = summaries[0]
    assert not row.skipped
    assert row.candidate_scores == [(0.92, 0.85), (0.91, 0.94)]
    assert row.svg_path.is_file()
    assert row.render_path.is_file()
    assert 'id="b"' in row.svg_path.read_text(encoding="utf-8"), (
        "LPIPS tiebreak should have selected candidate b (higher lpips, dino within band)"
    )
