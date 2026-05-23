from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.config import get_settings
from app.services import orchestrator


def test_pick_best_candidate_prefers_higher_combined_score_for_logos():
    """For logos, rank by mean(dino, lpips), not dino alone.

    DinoScore captures global color/shape similarity; LPIPS captures local
    perceptual detail (letterforms, edges). Weighting them equally avoids the
    failure mode where a candidate wins on background color match while losing
    on letter crispness.
    """
    candidates = [
        orchestrator._Candidate(
            svg="<svg id='a'/>",
            dino=0.936,
            lpips=0.91,
            engine="starvector",
            tried=3,
        ),
        orchestrator._Candidate(
            svg="<svg id='b'/>",
            dino=0.930,
            lpips=0.95,
            engine="vtracer_smooth",
            tried=4,
        ),
    ]
    winner = orchestrator._pick_best_candidate(candidates, kind="logo")
    assert winner.engine == "vtracer_smooth"


def test_pick_best_candidate_picks_high_lpips_even_when_dino_gap_is_large():
    """Regression test for cleo: when one candidate dominates on LPIPS the
    visual result is better, so it should win even when DinoScore gap is wider
    than the old 0.02 tiebreak band.
    """
    candidates = [
        orchestrator._Candidate(
            svg="<svg id='sv'/>",
            dino=0.960,
            lpips=0.90,
            engine="starvector",
            tried=3,
        ),
        orchestrator._Candidate(
            svg="<svg id='vt'/>",
            dino=0.920,
            lpips=0.98,
            engine="vtracer_smooth",
            tried=4,
        ),
    ]
    winner = orchestrator._pick_best_candidate(candidates, kind="logo")
    assert winner.engine == "vtracer_smooth", (
        "for logos, combined (dino+lpips)/2 should rank vtracer_smooth higher: "
        "0.920+0.98=1.900 vs 0.960+0.90=1.860"
    )


def test_pick_best_candidate_with_cleo_screenshot_numbers_picks_vtracer():
    """Direct replay of the cleo screenshot numbers + this morning's debug run.

    StarVector wins dino but loses lpips; vtracer/vtracer_smooth have very
    similar combined scores but both should beat StarVector.
    """
    candidates = [
        orchestrator._Candidate(
            svg="<svg id='sv'/>", dino=0.951, lpips=0.962,
            engine="starvector", tried=3,
        ),
        orchestrator._Candidate(
            svg="<svg id='vt'/>", dino=0.929, lpips=0.987,
            engine="vtracer", tried=4,
        ),
        orchestrator._Candidate(
            svg="<svg id='sm'/>", dino=0.925, lpips=0.990,
            engine="vtracer_smooth", tried=4,
        ),
    ]
    winner = orchestrator._pick_best_candidate(candidates, kind="logo")
    assert winner.engine != "starvector", (
        "the cleo regression: starvector's 0.951 dino must not beat vtracer's "
        "(0.929 + 0.987) / 2 = 0.958"
    )


def test_pick_best_candidate_uses_pure_dino_for_photos():
    """Photos use raw DinoScore; LPIPS over-weights pixel-perfect edges which
    isn't the right signal for photographic content."""
    candidates = [
        orchestrator._Candidate(
            svg="<svg id='sv'/>",
            dino=0.936,
            lpips=0.91,
            engine="starvector",
            tried=3,
        ),
        orchestrator._Candidate(
            svg="<svg id='vt'/>",
            dino=0.930,
            lpips=0.95,
            engine="vtracer_smooth",
            tried=4,
        ),
    ]
    winner = orchestrator._pick_best_candidate(candidates, kind="photo")
    assert winner.engine == "starvector"


def test_pick_best_candidate_uses_pure_dino_for_illustrations():
    """Illustrations sit between photos and logos; we keep dino-only for them too.
    Only logos need the combined-score weighting because letterform precision is
    the dominant quality signal there."""
    candidates = [
        orchestrator._Candidate(
            svg="<svg id='sv'/>",
            dino=0.94,
            lpips=0.85,
            engine="starvector",
            tried=3,
        ),
        orchestrator._Candidate(
            svg="<svg id='vt'/>",
            dino=0.92,
            lpips=0.95,
            engine="vtracer_smooth",
            tried=4,
        ),
    ]
    winner = orchestrator._pick_best_candidate(candidates, kind="illustration")
    assert winner.engine == "starvector"


def _make_logo_png() -> bytes:
    """Synthetic 2-color logo: dark on light background, large enough for ResNet."""
    img = Image.new("RGB", (256, 256), (250, 245, 235))
    arr = np.array(img)
    arr[40:200, 40:200] = (40, 30, 25)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def test_vectorize_bytes_standard_quality_runs_fewer_refine_passes(
    monkeypatch: pytest.MonkeyPatch,
):
    """The Quality dropdown's 'Faster' option must actually run a cheaper pipeline.

    We assert by intercepting ``refine.iterative_refine`` and checking the
    ``max_passes`` keyword arg the orchestrator forwards. 'Faster' should pass a
    smaller cap than 'High'.
    """
    from app.services import refine as refine_module

    captured: dict[str, int] = {}

    def fake_iterative_refine(img, base_svg, width, height, *, max_passes=None, **kw):
        _ = img, width, height, kw
        captured["max_passes"] = max_passes if max_passes is not None else -1
        return refine_module.RefineResult(svg=base_svg, score=0.9, passes=0, coverage=0.0)

    monkeypatch.setattr(refine_module, "iterative_refine", fake_iterative_refine)
    monkeypatch.setattr(orchestrator.refine, "iterative_refine", fake_iterative_refine)

    out = orchestrator.vectorize_bytes(
        _make_logo_png(),
        quality="standard",
        engine="vtracer",
        fontless=True,
    )
    assert "max_passes" in captured, "orchestrator must pass max_passes explicitly"
    standard_cap = captured["max_passes"]

    captured.clear()
    out = orchestrator.vectorize_bytes(
        _make_logo_png(),
        quality="high",
        engine="vtracer",
        fontless=True,
    )
    high_cap = captured["max_passes"]
    _ = out

    assert standard_cap > 0 and high_cap > 0
    assert standard_cap < high_cap, (
        f"quality='standard' ({standard_cap} passes) should be cheaper than "
        f"quality='high' ({high_cap} passes); otherwise the dropdown does nothing"
    )


def test_vectorize_bytes_high_quality_respects_settings_cap(
    monkeypatch: pytest.MonkeyPatch,
):
    """High quality should pass approximately ``settings.refine_max_passes`` to refine
    (within +/- 1 to allow rounding), so global tuning still applies."""
    from app.services import refine as refine_module

    settings = get_settings()
    captured: dict[str, int] = {}

    def fake_iterative_refine(img, base_svg, width, height, *, max_passes=None, **kw):
        _ = img, width, height, kw
        captured["max_passes"] = max_passes if max_passes is not None else -1
        return refine_module.RefineResult(svg=base_svg, score=0.9, passes=0, coverage=0.0)

    monkeypatch.setattr(orchestrator.refine, "iterative_refine", fake_iterative_refine)

    orchestrator.vectorize_bytes(
        _make_logo_png(),
        quality="high",
        engine="vtracer",
        fontless=True,
    )
    assert abs(captured["max_passes"] - settings.refine_max_passes) <= 1


def test_vectorize_bytes_auto_engine_emits_monochrome_candidate_for_cleo_like_logo(
    monkeypatch: pytest.MonkeyPatch,
):
    """For high-contrast 2-color logos (like cleo), auto mode must also run the
    palette=2 monochrome pass. Without it, vtracer faithfully traces JPEG/AA color
    drift across letter glyphs, which is the visible 'not perfect' regression.

    StarVector is stubbed to unavailable because the CI host has no CUDA; only
    the orchestrator-level routing logic is under test here.
    """
    from app.services import starvector_engine

    def fake_starvector(*args, **kwargs):
        _ = args, kwargs
        raise starvector_engine.StarVectorUnavailable("test env has no GPU")

    monkeypatch.setattr(starvector_engine, "vectorize", fake_starvector)

    seen_engines: list[str] = []

    real_run_vtracer = orchestrator._run_vtracer
    real_run_smooth = orchestrator._run_vtracer_smooth

    def tracked_vtracer(img, w, h, kind):
        seen_engines.append("vtracer")
        return real_run_vtracer(img, w, h, kind)

    def tracked_smooth(img, w, h, kind):
        seen_engines.append("vtracer_smooth")
        return real_run_smooth(img, w, h, kind)

    monkeypatch.setattr(orchestrator, "_run_vtracer", tracked_vtracer)
    monkeypatch.setattr(orchestrator, "_run_vtracer_smooth", tracked_smooth)

    if hasattr(orchestrator, "_run_vtracer_mono"):
        real_mono = orchestrator._run_vtracer_mono

        def tracked_mono(img, w, h, kind):
            seen_engines.append("vtracer_mono")
            return real_mono(img, w, h, kind)

        monkeypatch.setattr(orchestrator, "_run_vtracer_mono", tracked_mono)

    orchestrator.vectorize_bytes(
        _make_logo_png(),
        quality="standard",
        engine="auto",
        fontless=True,
    )
    assert "vtracer_mono" in seen_engines, (
        "auto+monochrome-logo must trigger the dedicated 2-color tracing path"
    )


def _make_aa_monochrome_logo_png() -> bytes:
    """A 2-color logo with enough anti-aliasing to classify as 'illustration'.

    Reproduces the cleo bug: the underlying image is monochrome but JPEG/AA
    fragments push unique_colors above 32 so ``classify_image`` no longer
    returns 'logo'. ``is_monochrome_logo`` correctly says True regardless.
    """
    import io

    img = Image.new("RGB", (256, 256), (250, 245, 235))
    arr = np.array(img)
    arr[60:200, 60:200] = (40, 30, 25)
    rng = np.random.default_rng(7)
    edge = rng.integers(-50, 51, size=arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + edge, 0, 255).astype(np.uint8)
    arr[80:180, 80:180] = (40, 30, 25)
    arr[110:150, 110:150] = (250, 245, 235)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def test_vectorize_bytes_runs_mono_pass_for_monochrome_image_classified_as_illustration(
    monkeypatch: pytest.MonkeyPatch,
):
    """The cleo regression: ``classify_image`` returns 'illustration' (cleo has 64
    unique colors due to AA), but the underlying image is still 2-color. The
    orchestrator must promote to 'logo' so vtracer_mono runs and the mean-rank
    metric is used."""
    from app.services import preprocess, starvector_engine

    monkeypatch.setattr(
        starvector_engine, "vectorize",
        lambda *a, **kw: (_ for _ in ()).throw(
            starvector_engine.StarVectorUnavailable("no gpu in test")
        ),
    )
    monkeypatch.setattr(orchestrator.preprocess, "is_monochrome_logo", lambda arr: True)
    monkeypatch.setattr(orchestrator, "classify_image", lambda stats: "illustration")

    seen: list[str] = []
    real_mono = orchestrator._run_vtracer_mono

    def tracked_mono(img, w, h, kind):
        seen.append(kind)
        return real_mono(img, w, h, kind)

    monkeypatch.setattr(orchestrator, "_run_vtracer_mono", tracked_mono)

    orchestrator.vectorize_bytes(
        _make_logo_png(),
        quality="standard",
        engine="auto",
        fontless=True,
    )
    assert seen, (
        "vtracer_mono must run when is_monochrome_logo is True even if "
        "classify_image returned 'illustration' (the cleo bug)"
    )
    assert seen[0] == "logo", (
        "the kind passed to vtracer_mono must be promoted to 'logo' so the "
        "internal `if kind != 'logo': return None` guard does not skip it"
    )


def test_vectorize_bytes_emits_per_engine_score_messages(
    monkeypatch: pytest.MonkeyPatch,
):
    """The progress callback must receive a message containing per-engine scores
    after each engine finishes, so the user sees what each ran and what it
    scored instead of the vague 'Generating with StarVector' text."""
    from app.services import starvector_engine

    monkeypatch.setattr(
        starvector_engine, "vectorize",
        lambda *a, **kw: (_ for _ in ()).throw(
            starvector_engine.StarVectorUnavailable("no gpu in test")
        ),
    )

    messages: list[tuple[str, str]] = []

    def cb(phase: str, message: str) -> None:
        messages.append((phase, message))

    orchestrator.vectorize_bytes(
        _make_logo_png(),
        quality="standard",
        engine="auto",
        fontless=True,
        progress_callback=cb,
    )

    text = " ".join(m for _, m in messages).lower()
    assert "vtracer" in text
    assert any(
        "dino" in m.lower() and "lpips" in m.lower() for _, m in messages
    ), (
        f"expected at least one progress message to include 'dino=...' and "
        f"'lpips=...' but got: {[m for _, m in messages]}"
    )
    assert any("chose" in m.lower() or "winner" in m.lower() for _, m in messages), (
        "expected a 'Chose ...' / 'Winner: ...' message naming the winning engine"
    )


def test_vectorize_output_carries_candidate_scores_and_decision():
    """Each per-engine attempt's (dino, lpips) and the final selection rationale
    must be on ``VectorizeOutput`` so the frontend can render the breakdown
    after completion (not just the winner's metrics)."""
    out = orchestrator.vectorize_bytes(
        _make_logo_png(), quality="standard", engine="vtracer", fontless=True,
    )
    assert hasattr(out, "candidate_scores")
    assert isinstance(out.candidate_scores, list)
    assert len(out.candidate_scores) >= 1
    first = out.candidate_scores[0]
    assert {"engine", "dino", "lpips", "selected"} <= set(first.keys()), (
        f"each candidate_scores entry must have engine/dino/lpips/selected keys, "
        f"got {first.keys()}"
    )
    assert any(c["selected"] for c in out.candidate_scores), (
        "exactly one candidate must be marked selected"
    )
    assert hasattr(out, "decision") and isinstance(out.decision, str) and out.decision
