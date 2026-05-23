"""Diagnostic CLI: convert one image through every engine and dump comparison files.

Use this to investigate visual regressions (e.g. "the cleo logo used to look
perfect"). It writes the SVG and a rasterized PNG for each engine you ask for,
plus per-candidate scores when running StarVector, so you can open the PNGs
side-by-side and see exactly where letterforms drift.

Usage::

    cd backend
    python -m scripts.debug_image \
        --image tests/fixtures/cleo.png \
        --output-dir ../debug_out \
        --engines starvector vtracer vtracer_smooth \
        --starvector-k 5 \
        --refine

GPU-only StarVector is opt-in (``--engines starvector``). Without ``--refine``,
the loop just shows base engine output, which is what you want when isolating
whether refinement is causing a regression.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

VALID_ENGINES = ("starvector", "vtracer", "vtracer_smooth", "vtracer_mono")
DEFAULT_ENGINES = ("vtracer", "vtracer_smooth", "vtracer_mono")


@dataclass
class EngineSummary:
    """One engine's diagnostic output for the summary table."""

    engine: str
    dino_score: float
    lpips: float
    path_count: int
    refine_passes: int
    ms: int
    svg_path: Path
    render_path: Path
    candidate_scores: list[tuple[float, float]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="debug_image",
        description=(
            "Convert one image through each requested engine and dump SVG + "
            "rasterized PNG for visual comparison. Use to investigate "
            "regressions like 'the cleo logo used to look perfect'."
        ),
    )
    parser.add_argument(
        "--image", required=True, type=Path, help="Path to input image (PNG/JPG)."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Where to write per-engine SVGs and rendered PNGs.",
    )
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=VALID_ENGINES,
        default=list(DEFAULT_ENGINES),
        help=(
            "Engines to run. StarVector needs a CUDA GPU and is opt-in. "
            "Default: vtracer vtracer_smooth."
        ),
    )
    parser.add_argument(
        "--starvector-k",
        type=int,
        default=3,
        help="StarVector best-of-k attempts (default 3, matches 'Faster' quality).",
    )
    parser.add_argument(
        "--refine",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the residual-overlay refinement loop on the base SVG. "
        "Use --no-refine to see raw engine output.",
    )
    parsed = parser.parse_args(argv)
    parsed.engines = tuple(parsed.engines)
    return parsed


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def _engine_summary_skipped(
    engine: str, svg_path: Path, render_path: Path, reason: str
) -> EngineSummary:
    return EngineSummary(
        engine=engine,
        dino_score=0.0,
        lpips=0.0,
        path_count=0,
        refine_passes=0,
        ms=0,
        svg_path=svg_path,
        render_path=render_path,
        candidate_scores=[],
        skipped=True,
        skip_reason=reason,
    )


def _run_starvector_candidates(
    img: Image.Image, width: int, height: int, k: int
) -> tuple[str, float, float, int, list[tuple[float, float]]]:
    """Run StarVector k times, returning chosen SVG + scores + per-candidate (dino, lpips).

    Uses the module-level ``score_svg`` reference on ``starvector_engine`` so test
    monkeypatches in the unit suite can substitute fake scorers without GPU.
    """
    from app.services import starvector_engine

    model = starvector_engine._load_model()
    max_length = starvector_engine.get_settings().starvector_max_length
    score_svg = starvector_engine.score_svg

    scores: list[tuple[float, float]] = []
    candidates: list[starvector_engine._Candidate] = []
    for i in range(max(1, k)):
        try:
            svg = starvector_engine._generate_one(model, img, max_length=max_length)
        except Exception as exc:
            print(f"  candidate {i + 1}: generation failed: {exc}", file=sys.stderr)
            continue
        dino, lpips = score_svg(img, svg, width, height)
        scores.append((dino, lpips))
        candidates.append(starvector_engine._Candidate(svg=svg, dino=dino, lpips=lpips))
        print(f"  candidate {i + 1}: dino={dino:.4f} lpips={lpips:.4f}")

    if not candidates:
        raise starvector_engine.StarVectorUnavailable("All StarVector candidates failed")

    winner = starvector_engine._pick_best_candidate(candidates)
    return winner.svg, winner.dino, winner.lpips, len(candidates), scores


def _run_vtracer_engine(
    img: Image.Image, width: int, height: int, mode: str
) -> tuple[str, float, float]:
    """Trace ``img`` with one vtracer variant. ``mode`` is 'plain', 'smooth', or 'mono'."""
    from app.services import preprocess, vtracer_engine
    from app.services.dino_score import score_svg
    from app.services.preprocess import classify_image, image_stats
    import numpy as np

    arr = np.array(img.convert("RGBA"))
    stats = image_stats(arr)
    kind = classify_image(stats)

    if mode == "smooth":
        cleaned = preprocess.clean_for_tracing(img, kind=kind, palette_size=6)
        svg, _ = vtracer_engine.auto_tune(
            cleaned, width, height, grid=vtracer_engine.LOGO_SMOOTH_GRID
        )
    elif mode == "mono":
        cleaned = preprocess.clean_for_tracing(img, kind="logo", palette_size=2)
        svg, _ = vtracer_engine.auto_tune(
            cleaned, width, height, grid=vtracer_engine.LOGO_MONO_GRID
        )
    else:
        grid = vtracer_engine.LOGO_GRID if kind == "logo" else vtracer_engine.DEFAULT_GRID
        svg, _ = vtracer_engine.auto_tune(img, width, height, grid=grid)

    dino, lpips = score_svg(img, svg, width, height)
    return svg, dino, lpips


def _maybe_refine(
    img: Image.Image, base_svg: str, width: int, height: int, do_refine: bool
) -> tuple[str, float, float, int]:
    from app.services import refine
    from app.services.dino_score import score_svg

    if not do_refine:
        dino, lpips = score_svg(img, base_svg, width, height)
        return base_svg, dino, lpips, 0

    result = refine.iterative_refine(img, base_svg, width, height)
    dino, lpips = score_svg(img, result.svg, width, height)
    return result.svg, dino, lpips, result.passes


def _count_paths(svg: str) -> int:
    from app.services.svg_raster import count_paths

    return count_paths(svg)


def _rasterize_to(svg: str, width: int, height: int, dest: Path) -> None:
    from app.services.svg_raster import rasterize_svg

    rasterize_svg(svg, width, height).save(dest, format="PNG")


def run(
    *,
    image_path: Path,
    output_dir: Path,
    engines: tuple[str, ...],
    starvector_k: int,
    refine: bool,
) -> list[EngineSummary]:
    """Run each engine and write per-engine SVG + rasterized PNG to ``output_dir``.

    Returns a list of ``EngineSummary`` rows in the same order as ``engines``.
    Failed/unavailable engines produce a row with ``skipped=True`` rather than
    aborting the whole run, so you still see results for the engines that did
    work.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(image_path).convert("RGBA")
    width, height = img.size

    rows: list[EngineSummary] = []
    for engine in engines:
        engine_safe = _safe_filename(engine)
        svg_path = output_dir / f"{engine_safe}.svg"
        render_path = output_dir / f"{engine_safe}.render.png"

        print(f"\n=== {engine} ===")
        start = time.perf_counter()
        candidate_scores: list[tuple[float, float]] = []
        try:
            if engine == "starvector":
                base_svg, _, _, _, candidate_scores = _run_starvector_candidates(
                    img, width, height, starvector_k
                )
            elif engine == "vtracer":
                base_svg, _, _ = _run_vtracer_engine(img, width, height, mode="plain")
            elif engine == "vtracer_smooth":
                base_svg, _, _ = _run_vtracer_engine(img, width, height, mode="smooth")
            elif engine == "vtracer_mono":
                base_svg, _, _ = _run_vtracer_engine(img, width, height, mode="mono")
            else:
                rows.append(
                    _engine_summary_skipped(
                        engine, svg_path, render_path, f"unknown engine: {engine}"
                    )
                )
                continue
        except Exception as exc:
            print(f"  {engine} failed: {exc}", file=sys.stderr)
            rows.append(_engine_summary_skipped(engine, svg_path, render_path, str(exc)))
            continue

        final_svg, dino, lpips, passes = _maybe_refine(
            img, base_svg, width, height, do_refine=refine
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        svg_path.write_text(final_svg, encoding="utf-8")
        _rasterize_to(final_svg, width, height, render_path)

        rows.append(
            EngineSummary(
                engine=engine,
                dino_score=dino,
                lpips=lpips,
                path_count=_count_paths(final_svg),
                refine_passes=passes,
                ms=elapsed_ms,
                svg_path=svg_path,
                render_path=render_path,
                candidate_scores=candidate_scores,
            )
        )
        print(
            f"  dino={dino:.4f} lpips={lpips:.4f} paths={_count_paths(final_svg)} "
            f"refine_passes={passes} time={elapsed_ms} ms"
        )
        print(f"  wrote {svg_path} + {render_path}")

    return rows


def format_summary_table(rows: list[EngineSummary]) -> str:
    """Build a human-readable summary suitable for printing at the end of the run."""
    if not rows:
        return "(no engines ran)"

    header = (
        f"{'engine':<16}{'dino':>9}{'lpips':>9}{'paths':>8}"
        f"{'refine':>9}{'ms':>9}  notes"
    )
    lines = [header, "-" * (len(header) + 4)]
    for r in rows:
        if r.skipped:
            lines.append(
                f"{r.engine:<16}{'-':>9}{'-':>9}{'-':>8}{'-':>9}{'-':>9}  "
                f"SKIPPED: {r.skip_reason}"
            )
            continue
        lines.append(
            f"{r.engine:<16}{r.dino_score:>9.4f}{r.lpips:>9.4f}"
            f"{r.path_count:>8d}{r.refine_passes:>9d}{r.ms:>9d}  "
            f"{r.render_path.name}"
        )
        if r.candidate_scores:
            cand_str = ", ".join(
                f"({d:.4f},{l:.4f})" for d, l in r.candidate_scores
            )
            lines.append(f"  candidates (dino,lpips): {cand_str}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.image.is_file():
        print(f"error: image not found: {args.image}", file=sys.stderr)
        return 2

    rows = run(
        image_path=args.image,
        output_dir=args.output_dir,
        engines=args.engines,
        starvector_k=args.starvector_k,
        refine=args.refine,
    )
    print("\n=== summary ===")
    print(format_summary_table(rows))
    print(f"\nOutput dir: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
