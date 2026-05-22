from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from PIL import Image

from app.config import EngineChoice, QualityTier, get_settings
from app.services import preprocess, refine, starvector_engine, vtracer_engine
from app.services.dino_score import score_svg
from app.services.fontless import enforce_fontless
from app.services.preprocess import classify_image, image_stats, load_image_bytes
from app.services.svg_raster import count_paths

logger = logging.getLogger(__name__)


# Human-readable label for each backend phase. Frontend can render its own
# labels but having defaults here keeps logs and CLI-consumers readable too.
_PHASE_LABELS: dict[str, str] = {
    "queued": "Queued",
    "fetching": "Downloading image",
    "preprocessing": "Analyzing image",
    "starvector": "Generating with StarVector",
    "vtracer": "Tracing with VTracer",
    "vtracer_smooth": "Smoothing curves",
    "refining": "Refining details",
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


def _run_starvector(
    img: Image.Image, width: int, height: int, k: int, required: bool
) -> _Candidate | None:
    try:
        sv = starvector_engine.vectorize(img, width, height, k=k)
    except starvector_engine.StarVectorUnavailable:
        if required:
            raise
        return None
    _, lpips = score_svg(img, sv.svg, width, height)
    return _Candidate(
        svg=sv.svg,
        dino=sv.dino_score,
        lpips=lpips,
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
    img, arr = load_image_bytes(data, settings.max_image_dimension)
    width, height = img.size
    stats = image_stats(arr)
    kind = classify_image(stats)
    k = settings.starvector_k_high if quality == "high" else settings.starvector_k_standard

    candidates: list[_Candidate] = []

    if engine in ("auto", "starvector"):
        report("starvector")
        sv = _run_starvector(img, width, height, k, required=engine == "starvector")
        if sv:
            candidates.append(sv)

    run_vtracer = engine == "vtracer" or (
        engine == "auto" and (settings.auto_use_ensemble or not candidates)
    )
    if run_vtracer:
        report("vtracer")
        vt = _run_vtracer(img, width, height, kind)
        if vt:
            candidates.append(vt)

    run_smooth = engine == "vtracer_smooth" or (
        engine == "auto" and settings.vtracer_smooth_enabled and kind != "photo"
    )
    if run_smooth:
        report("vtracer_smooth")
        sm = _run_vtracer_smooth(img, width, height, kind)
        if sm:
            candidates.append(sm)
        elif engine == "vtracer_smooth":
            raise RuntimeError("Smooth-curve VTracer pipeline produced no output")

    if not candidates:
        raise RuntimeError("Vectorization produced no output")

    candidates.sort(key=lambda c: c.dino, reverse=True)
    base = candidates[0]
    total_tried = sum(c.tried for c in candidates)

    base_dino = base.dino
    final_svg = base.svg
    final_dino = base.dino
    final_lpips = base.lpips
    refine_passes = 0
    refine_coverage = 0.0

    if settings.refine_enabled:
        report("refining")
        try:
            result = refine.iterative_refine(img, base.svg, width, height)
        except Exception as exc:
            logger.warning("refinement failed, keeping base SVG: %s", exc)
            result = None
        if result and result.passes > 0:
            final_svg = result.svg
            final_dino = result.score
            _, final_lpips = score_svg(img, final_svg, width, height)
            refine_passes = result.passes
            refine_coverage = result.coverage

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
    )
