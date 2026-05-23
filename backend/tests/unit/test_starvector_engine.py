from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.services import starvector_engine


def test_is_winerror_6714_direct_oserror():
    exc = OSError(6714, "transaction context is not valid")
    assert starvector_engine._is_winerror_6714(exc) is True


def test_is_winerror_6714_import_error_with_cause():
    exc = ImportError("Failed to import transformers")
    exc.__cause__ = OSError(6714, "transaction context is not valid")
    assert starvector_engine._is_winerror_6714(exc) is True


def test_is_winerror_6714_message_fallback():
    exc = ImportError("[WinError 6714] stale reload worker")
    assert starvector_engine._is_winerror_6714(exc) is True


def test_is_winerror_6714_unrelated_oserror():
    exc = OSError(2, "file not found")
    assert starvector_engine._is_winerror_6714(exc) is False


def test_is_winerror_6714_unrelated_import_error():
    exc = ImportError("No module named 'starvector'")
    assert starvector_engine._is_winerror_6714(exc) is False


def test_wrap_starvector_import_error_maps_6714_to_unavailable():
    exc = ImportError("[WinError 6714] stale reload worker")
    with pytest.raises(starvector_engine.StarVectorUnavailable) as err:
        starvector_engine._wrap_starvector_import_error(exc)
    assert "6714" in str(err.value)
    assert "run.ps1" in str(err.value)


def test_wrap_starvector_import_error_keeps_missing_package_message():
    exc = ImportError("No module named 'starvector'")
    with pytest.raises(starvector_engine.StarVectorUnavailable) as err:
        starvector_engine._wrap_starvector_import_error(exc)
    assert "not installed" in str(err.value)


def test_pick_best_candidate_keeps_high_dino_winner_when_gap_is_large():
    """When one candidate dominates on DinoScore, keep it even if LPIPS is lower.

    DinoScore is the primary fidelity signal; LPIPS only breaks ties for nearly
    indistinguishable candidates.
    """
    candidates = [
        starvector_engine._Candidate(svg="<svg>winner</svg>", dino=0.96, lpips=0.88),
        starvector_engine._Candidate(svg="<svg>loser</svg>", dino=0.91, lpips=0.97),
    ]
    winner = starvector_engine._pick_best_candidate(candidates)
    assert winner.svg == "<svg>winner</svg>"


def test_pick_best_candidate_breaks_close_dino_tie_with_lpips():
    """Two near-identical DinoScores: take the one with crisper local detail (higher LPIPS).

    This is the regression guard for stochastic StarVector runs where one candidate
    has slightly-distorted letterforms but matching background colors (high dino,
    lower lpips) and another has crisp letterforms (slightly lower dino, higher lpips).
    The original best-by-dino-only logic would silently pick the distorted one.
    """
    candidates = [
        starvector_engine._Candidate(svg="<svg>distorted</svg>", dino=0.952, lpips=0.88),
        starvector_engine._Candidate(svg="<svg>crisp</svg>", dino=0.948, lpips=0.97),
    ]
    winner = starvector_engine._pick_best_candidate(candidates)
    assert winner.svg == "<svg>crisp</svg>"


def test_pick_best_candidate_handles_single_candidate():
    candidates = [
        starvector_engine._Candidate(svg="<svg>only</svg>", dino=0.5, lpips=0.5),
    ]
    winner = starvector_engine._pick_best_candidate(candidates)
    assert winner.svg == "<svg>only</svg>"


def test_pick_best_candidate_raises_on_empty():
    with pytest.raises(ValueError):
        starvector_engine._pick_best_candidate([])


def test_vectorize_selects_best_candidate_via_tiebreak(monkeypatch: pytest.MonkeyPatch):
    """Drive vectorize() with three fake generations and verify selection.

    All three are within the LPIPS-tiebreak band on DinoScore. The middle one
    has the best LPIPS, so it must win even though it doesn't have the top
    DinoScore. This is the end-to-end check for the cleo regression.
    """
    fake_svgs = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" id="a"/>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" id="b"/>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" id="c"/>',
    ]
    scores = {
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" id="a"/>': (0.951, 0.88),
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" id="b"/>': (0.948, 0.97),
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" id="c"/>': (0.940, 0.90),
    }
    call_count = {"i": 0}

    def fake_load_model():
        return object()

    def fake_generate_one(_model, _img, max_length):
        _ = max_length
        svg = fake_svgs[call_count["i"]]
        call_count["i"] += 1
        return svg

    def fake_score_svg(_img, svg, _w, _h):
        return scores[svg]

    monkeypatch.setattr(starvector_engine, "_load_model", fake_load_model)
    monkeypatch.setattr(starvector_engine, "_generate_one", fake_generate_one)
    monkeypatch.setattr(starvector_engine, "score_svg", fake_score_svg)

    img = Image.new("RGB", (10, 10), (255, 255, 255))
    result = starvector_engine.vectorize(img, 10, 10, k=3)

    assert result.svg == '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" id="b"/>'
    assert result.dino_score == pytest.approx(0.948)
    assert result.lpips == pytest.approx(0.97)
    assert result.candidates_tried == 3


def test_vectorize_skips_failed_generations(monkeypatch: pytest.MonkeyPatch):
    """One generation raises; vectorize() still returns the surviving candidates' best."""
    outcomes = [
        ("good", 0.92, 0.95),
        ("boom", None, None),
        ("ok", 0.90, 0.91),
    ]
    state = {"i": 0}

    def fake_load_model():
        return object()

    def fake_generate_one(_model, _img, max_length):
        _ = max_length
        label, _d, _l = outcomes[state["i"]]
        state["i"] += 1
        if label == "boom":
            raise RuntimeError("simulated decode failure")
        return f'<svg id="{label}"/>'

    def fake_score_svg(_img, svg, _w, _h):
        for label, d, l in outcomes:
            if label and f'id="{label}"' in svg:
                return d, l
        return 0.0, 0.0

    monkeypatch.setattr(starvector_engine, "_load_model", fake_load_model)
    monkeypatch.setattr(starvector_engine, "_generate_one", fake_generate_one)
    monkeypatch.setattr(starvector_engine, "score_svg", fake_score_svg)

    img = Image.new("RGB", (10, 10), (255, 255, 255))
    result = starvector_engine.vectorize(img, 10, 10, k=3)

    assert result.candidates_tried == 2
    assert 'id="good"' in result.svg


def test_vectorize_raises_when_all_candidates_fail(monkeypatch: pytest.MonkeyPatch):
    def fake_load_model():
        return object()

    def always_raise(_model, _img, max_length):
        _ = max_length
        raise RuntimeError("boom")

    monkeypatch.setattr(starvector_engine, "_load_model", fake_load_model)
    monkeypatch.setattr(starvector_engine, "_generate_one", always_raise)

    img = Image.new("RGB", (10, 10), (255, 255, 255))
    with pytest.raises(starvector_engine.StarVectorUnavailable):
        starvector_engine.vectorize(img, 10, 10, k=2)


def test_cleo_fixture_is_a_valid_logo_image():
    """The cleo benchmark image must remain available for visual regression checks."""
    fixture = Path(__file__).resolve().parent.parent / "fixtures" / "cleo.png"
    assert fixture.is_file(), "expected backend/tests/fixtures/cleo.png to be checked in"
    with Image.open(fixture) as img:
        assert img.width > 0 and img.height > 0
        assert img.format == "PNG"
