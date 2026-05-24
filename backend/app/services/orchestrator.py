from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from PIL import Image

from app.config import EngineChoice, QualityTier, get_settings
from app.services import (
    preprocess,
    refine,
    smooth_paths,
    starvector_engine,
    vtracer_engine,
)
from app.services.dino_score import score_svg
from app.services.fontless import enforce_fontless
from app.services.preprocess import (
    classify_image,
    dimension_cap_for_kind,
    image_stats,
    load_image_bytes,
    validate_image_limits,
)
from app.services.svg_raster import count_paths

logger = logging.getLogger(__name__)


# Refinement budget per quality tier. The Quality dropdown's 'Faster' / 'High'
# options need observable behavior; just scaling starvector_k from 3->5 is too
# subtle. Capping (or expanding) the refinement loop is the most visible knob.
_REFINE_MAX_PASSES_BY_QUALITY: dict[str, int] = {
    "standard": 8,
}


def _refine_passes_for_quality(quality: str, settings_cap: int) -> int:
    if quality == "high":
        return settings_cap
    return min(_REFINE_MAX_PASSES_BY_QUALITY.get(quality, 8), settings_cap)


# Human-readable label for each backend phase. Frontend can render its own
# labels but having defaults here keeps logs and CLI-consumers readable too.
_PHASE_LABELS: dict[str, str] = {
    "queued": "Queued",
    "fetching": "Downloading image",
    "preprocessing": "Analyzing image",
    "starvector": "Generating with StarVector",
    "vtracer": "Tracing with VTracer",
    "vtracer_smooth": "Smoothing curves",
    "vtracer_mono": "Tracing 2-color logo",
    "refining": "Refining details",
    "smoothing": "Smoothing edges",
    "sanitizing": "Cleaning up SVG",
    "done": "Done",
    "failed": "Failed",
}


# ``progress_callback`` historically took a single string. We now support either:
#   - ``cb(phase: str, message: str)`` (preferred)
#   - ``cb(phase_or_message: str)`` (backwards-compatible fallback)
ProgressCallback = Callable[..., None]


@dataclass
class _Candidate:
    svg: str
    dino: float
    lpips: float
    engine: str
    tried: int


@dataclass
class VectorizeOutput:
    svg: str
    width: int
    height: int
    dino_score: float
    lpips: float
    engine: str
    candidates_tried: int
    path_count: int
    ms: int
    base_dino_score: float | None = None
    refine_passes: int = 0
    refine_coverage: float = 0.0
    candidate_scores: list[dict] = field(default_factory=list)
    decision: str = ""
    smoothing_applied: bool = False
    smoothing_method: str = "none"
    smoothing_delta: float = 0.0


def _pick_best_candidate(candidates: list[_Candidate], kind: str) -> _Candidate:
    """Return the ensemble winner using a kind-aware ranking metric.

    Logos: rank by ``(dino + lpips) / 2`` so candidates with crisper local
    detail (letterforms, edges) win even when their DinoScore is lower than a
    competitor's. Empirically DinoScore alone over-weights global color match
    and lets letter distortion through, which is the cleo regression.

    Non-logos: rank by DinoScore alone. LPIPS over-rewards pixel-perfect edge
    fidelity, which is the wrong signal for photographic / illustrative content.
    """
    if not candidates:
        raise ValueError("_pick_best_candidate requires at least one candidate")

    def score(c: _Candidate) -> float:
        if kind == "logo":
            return (c.dino + c.lpips) / 2.0
        return c.dino

    ranked = sorted(candidates, key=score, reverse=True)
    winner = ranked[0]
    dino_ranked = sorted(candidates, key=lambda c: c.dino, reverse=True)
    if kind == "logo" and len(candidates) >= 2 and winner is not dino_ranked[0]:
        top_dino = dino_ranked[0]
        logger.info(
            "logo ranking: chose %s (dino=%.4f lpips=%.4f mean=%.4f) over %s "
            "(dino=%.4f lpips=%.4f mean=%.4f)",
            winner.engine, winner.dino, winner.lpips, score(winner),
            top_dino.engine, top_dino.dino, top_dino.lpips, score(top_dino),
        )
    return winner


def _run_starvector(
    img: Image.Image, width: int, height: int, k: int, required: bool
) -> _Candidate | None:
    try:
        sv = starvector_engine.vectorize(img, width, height, k=k)
    except starvector_engine.StarVectorUnavailable:
        if required:
            raise
        return None
    return _Candidate(
        svg=sv.svg,
        dino=sv.dino_score,
        lpips=sv.lpips,
        engine="starvector",
        tried=sv.candidates_tried,
    )


def _run_vtracer(
    img: Image.Image, width: int, height: int, kind: str
) -> _Candidate | None:
    grid = vtracer_engine.LOGO_GRID if kind == "logo" else vtracer_engine.DEFAULT_GRID
    try:
        svg, dino = vtracer_engine.auto_tune(img, width, height, grid=grid)
    except Exception as exc:
        logger.warning("VTracer auto-tune failed: %s", exc)
        return None
    _, lpips = score_svg(img, svg, width, height)
    return _Candidate(svg=svg, dino=dino, lpips=lpips, engine="vtracer", tried=len(grid))


def _run_vtracer_mono(
    img: Image.Image, width: int, height: int, kind: str
) -> _Candidate | None:
    """Binary 2-color tracing pass for monochrome logos (e.g. cleo).

    Two-color brand marks are the worst case for the standard smooth pipeline:
    palette=6 cleaning preserves anti-aliasing color drift across letterforms,
    so vtracer traces every glyph in a slightly different shade and adds tiny
    sub-pixel sliver paths along AA edges. This pass instead snaps to *exactly*
    2 colors so the entire foreground collapses to a single fill, then traces
    in binary mode for a clean few-path output.

    Returns ``None`` for non-logo images (or if the pipeline fails) so the
    orchestrator can ignore it without raising.
    """
    if kind != "logo":
        return None
    try:
        cleaned = preprocess.clean_for_tracing(
            img,
            kind="logo",
            palette_size=2,
            bilateral=True,
        )
        svg, _ = vtracer_engine.auto_tune(
            cleaned, width, height, grid=vtracer_engine.LOGO_MONO_GRID
        )
    except Exception as exc:
        logger.warning("VTracer monochrome pass failed: %s", exc)
        return None

    dino, lpips = score_svg(img, svg, width, height)
    return _Candidate(
        svg=svg,
        dino=dino,
        lpips=lpips,
        engine="vtracer_mono",
        tried=len(vtracer_engine.LOGO_MONO_GRID),
    )


def _run_vtracer_smooth(
    img: Image.Image, width: int, height: int, kind: str
) -> _Candidate | None:
    """VTracer over a palette-quantized + denoised version of the image.

    By snapping every pixel to a small palette before tracing, VTracer sees
    perfectly-flat color regions with crisp edges instead of JPEG/AA noise,
    so it produces smoother curves with far fewer control points. The output
    is still scored against the *original* image so it competes fairly with
    the noisy-input candidates in the ensemble.
    """
    settings = get_settings()
    if not settings.vtracer_smooth_enabled or kind == "photo":
        return None
    try:
        cleaned = preprocess.clean_for_tracing(
            img,
            kind=kind,
            palette_size=settings.vtracer_smooth_palette_size,
            bilateral=settings.vtracer_smooth_bilateral,
        )
        svg, _ = vtracer_engine.auto_tune(
            cleaned, width, height, grid=vtracer_engine.LOGO_SMOOTH_GRID
        )
    except Exception as exc:
        logger.warning("VTracer smooth pass failed: %s", exc)
        return None

    dino, lpips = score_svg(img, svg, width, height)
    return _Candidate(
        svg=svg,
        dino=dino,
        lpips=lpips,
        engine="vtracer_smooth",
        tried=len(vtracer_engine.LOGO_SMOOTH_GRID),
    )


def vectorize_bytes(
    data: bytes,
    *,
    quality: QualityTier = "standard",
    engine: EngineChoice = "auto",
    fontless: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> VectorizeOutput:
    settings = get_settings()
    started = time.perf_counter()

    def report(phase: str, message: str | None = None) -> None:
        if not progress_callback:
            return
        msg = message or _PHASE_LABELS.get(phase, phase)
        try:
            progress_callback(phase, msg)
        except TypeError:
            # Older callers (single-arg) still get a usable string.
            progress_callback(msg)

    report("preprocessing")
    probed_kind = validate_image_limits(data, settings)
    cap = dimension_cap_for_kind(probed_kind, settings)
    img, arr = load_image_bytes(data, cap)
    width, height = img.size
    stats = image_stats(arr)
    raw_kind = classify_image(stats)
    is_mono = preprocess.is_monochrome_logo(arr)
    # Cleo-style logos have AA fragments that push unique_colors above 32 so
    # classify_image returns 'illustration'. is_monochrome_logo bucket-counts the
    # underlying colors and correctly says 'this is effectively 2 tones'; we
    # promote those images to 'logo' so the logo-specific routing (mono pass,
    # mean-rank metric) actually runs.
    kind = "logo" if is_mono else raw_kind
    detected = (
        f"Detected: {kind} ({stats['unique_colors']} unique colors, "
        f"edge_density={stats['edge_density']:.3f}"
        + (", monochrome" if is_mono else "")
        + ")"
    )
    report("preprocessing", detected)
    logger.info(detected)
    k = settings.starvector_k_high if quality == "high" else settings.starvector_k_standard

    candidates: list[_Candidate] = []

    def _announce(candidate: _Candidate | None, engine_label: str, phase: str) -> None:
        if candidate is None:
            report(phase, f"{engine_label}: no output (skipped)")
            return
        report(
            phase,
            f"{engine_label}: dino={candidate.dino:.3f} "
            f"lpips={candidate.lpips:.3f} mean={(candidate.dino + candidate.lpips) / 2:.3f}",
        )

    if engine in ("auto", "starvector"):
        report("starvector", f"StarVector: running {k} candidate(s)...")
        sv = _run_starvector(img, width, height, k, required=engine == "starvector")
        if sv:
            candidates.append(sv)
        _announce(sv, "StarVector", "starvector")

    run_vtracer = engine == "vtracer" or (
        engine == "auto" and (settings.auto_use_ensemble or not candidates)
    )
    if run_vtracer:
        report("vtracer", "VTracer: tracing...")
        vt = _run_vtracer(img, width, height, kind)
        if vt:
            candidates.append(vt)
        _announce(vt, "VTracer", "vtracer")

    run_smooth = engine == "vtracer_smooth" or (
        engine == "auto" and settings.vtracer_smooth_enabled and kind != "photo"
    )
    if run_smooth:
        report("vtracer_smooth", "VTracer smooth: palette + smooth-curve tracing...")
        sm = _run_vtracer_smooth(img, width, height, kind)
        if sm:
            candidates.append(sm)
        elif engine == "vtracer_smooth":
            raise RuntimeError("Smooth-curve VTracer pipeline produced no output")
        _announce(sm, "VTracer smooth", "vtracer_smooth")

    run_mono = engine == "vtracer_mono" or (
        engine == "auto" and kind == "logo"
    )
    if run_mono:
        report("vtracer_mono", "VTracer monochrome: palette=2 binary trace...")
        mn = _run_vtracer_mono(img, width, height, kind)
        if mn:
            candidates.append(mn)
        elif engine == "vtracer_mono":
            raise RuntimeError("Monochrome VTracer pipeline produced no output")
        _announce(mn, "VTracer monochrome", "vtracer_mono")

    if not candidates:
        raise RuntimeError("Vectorization produced no output")

    base = _pick_best_candidate(candidates, kind)
    total_tried = sum(c.tried for c in candidates)

    rank_label = (
        "mean(dino,lpips)" if kind == "logo" else "dino"
    )
    if kind == "logo":
        winner_score = (base.dino + base.lpips) / 2
    else:
        winner_score = base.dino
    decision = (
        f"Winner: {base.engine} ({rank_label}={winner_score:.3f}) "
        f"out of {len(candidates)} engine(s)"
    )
    report("refining", decision)
    logger.info(decision)

    base_dino = base.dino
    final_svg = base.svg
    final_dino = base.dino
    final_lpips = base.lpips
    refine_passes = 0
    refine_coverage = 0.0

    refine_cap = _refine_passes_for_quality(quality, settings.refine_max_passes)
    try:
        result = refine.iterative_refine(
            img, base.svg, width, height, max_passes=refine_cap
        )
    except Exception as exc:
        logger.warning("refinement failed, keeping base SVG: %s", exc)
        result = None
    if result and result.passes > 0:
        final_svg = result.svg
        final_dino = result.score
        _, final_lpips = score_svg(img, final_svg, width, height)
        refine_passes = result.passes
        refine_coverage = result.coverage
        report(
            "refining",
            f"Refinement accepted {refine_passes} pass(es), "
            f"final dino={final_dino:.3f} lpips={final_lpips:.3f}",
        )
    else:
        report("refining", "Refinement: no overlays improved the base SVG")

    smoothing_applied = False
    smoothing_method = "none"
    smoothing_delta = 0.0
    if settings.path_smoothing_enabled and kind != "photo":
        report("smoothing", "Smoothing edges...")

        def _smoothing_score(candidate_svg: str) -> float:
            dino_val, _ = score_svg(img, candidate_svg, width, height)
            return dino_val

        try:
            smoothed_svg, method, delta = smooth_paths.smooth_svg(
                final_svg,
                width,
                height,
                kind=kind,
                score_fn=_smoothing_score,
                settings=settings,
                source_image=img,
            )
        except Exception as exc:
            logger.warning("smoothing pass failed, keeping refined SVG: %s", exc)
            smoothed_svg, method, delta = final_svg, "none", 0.0

        smoothing_method = method
        smoothing_delta = float(delta)
        if method != "none":
            final_svg = smoothed_svg
            final_dino, final_lpips = score_svg(img, final_svg, width, height)
            smoothing_applied = True
            report(
                "smoothing",
                f"Smoothing accepted via {method} "
                f"(dino {final_dino:.3f}, delta {delta:+.3f})",
            )
        else:
            report(
                "smoothing",
                "Smoothing: no method improved the SVG, kept refined output",
            )
    else:
        reason = "kind=photo" if kind == "photo" else "disabled"
        report("smoothing", f"Smoothing skipped ({reason})")

    report("sanitizing")

    if fontless:
        try:
            final_svg = enforce_fontless(final_svg)
        except ValueError as exc:
            logger.warning("fontless sanitize failed (%s); using base SVG", exc)
            final_svg = enforce_fontless(base.svg)
            final_dino = base.dino
            final_lpips = base.lpips
            refine_passes = 0
            refine_coverage = 0.0
            smoothing_applied = False
            smoothing_method = "none"
            smoothing_delta = 0.0

    candidate_scores = [
        {
            "engine": c.engine,
            "dino": round(c.dino, 4),
            "lpips": round(c.lpips, 4),
            "mean": round((c.dino + c.lpips) / 2, 4),
            "selected": c is base,
            "tried": c.tried,
        }
        for c in candidates
    ]

    ms = int((time.perf_counter() - started) * 1000)
    return VectorizeOutput(
        svg=final_svg,
        width=width,
        height=height,
        dino_score=final_dino,
        lpips=final_lpips,
        engine=base.engine,
        candidates_tried=total_tried,
        path_count=count_paths(final_svg),
        ms=ms,
        base_dino_score=base_dino,
        refine_passes=refine_passes,
        refine_coverage=refine_coverage,
        candidate_scores=candidate_scores,
        decision=decision,
        smoothing_applied=smoothing_applied,
        smoothing_method=smoothing_method,
        smoothing_delta=smoothing_delta,
    )
