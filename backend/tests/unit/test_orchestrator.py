from __future__ import annotations

from app.services import orchestrator


def test_pick_best_candidate_prefers_lpips_on_close_logo_scores():
    candidates = [
        orchestrator._Candidate(
            svg="<svg/>",
            dino=0.936,
            lpips=0.91,
            engine="starvector",
            tried=3,
        ),
        orchestrator._Candidate(
            svg="<svg/>",
            dino=0.930,
            lpips=0.95,
            engine="vtracer_smooth",
            tried=4,
        ),
    ]
    winner = orchestrator._pick_best_candidate(candidates, kind="logo")
    assert winner.engine == "vtracer_smooth"


def test_pick_best_candidate_keeps_top_dino_when_gap_is_large():
    candidates = [
        orchestrator._Candidate(
            svg="<svg/>",
            dino=0.960,
            lpips=0.90,
            engine="starvector",
            tried=3,
        ),
        orchestrator._Candidate(
            svg="<svg/>",
            dino=0.920,
            lpips=0.98,
            engine="vtracer_smooth",
            tried=4,
        ),
    ]
    winner = orchestrator._pick_best_candidate(candidates, kind="logo")
    assert winner.engine == "starvector"


def test_pick_best_candidate_ignores_tiebreak_for_photos():
    candidates = [
        orchestrator._Candidate(
            svg="<svg/>",
            dino=0.936,
            lpips=0.91,
            engine="starvector",
            tried=3,
        ),
        orchestrator._Candidate(
            svg="<svg/>",
            dino=0.930,
            lpips=0.95,
            engine="vtracer_smooth",
            tried=4,
        ),
    ]
    winner = orchestrator._pick_best_candidate(candidates, kind="photo")
    assert winner.engine == "starvector"
