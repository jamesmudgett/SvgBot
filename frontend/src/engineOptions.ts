import type { EngineChoice } from "./api/client";

export type EngineOption = {
  value: EngineChoice;
  /** Short label for the &lt;select&gt; option */
  selectLabel: string;
  /** Best-for tag shown in docs */
  bestFor: string;
  /** Longer copy for the info section */
  description: string;
};

export const DEFAULT_ENGINE: EngineChoice = "auto";

export const ENGINE_OPTIONS: EngineOption[] = [
  {
    value: "auto",
    selectLabel: "Auto (default, runs all engines, picks best score)",
    bestFor: "Maximum accuracy when you can wait",
    description:
      "Generates one candidate from each engine, ranks logos by mean(DinoScore, LPIPS) so crisper letterforms win, ranks photos by DinoScore, then refines the winner. For high-contrast 2-color brand marks, also runs a dedicated palette=2 binary trace. Default choice: slowest but best when you are unsure which engine fits the image.",
  },
  {
    value: "vtracer_mono",
    selectLabel: "VTracer monochrome (best for 2-color logos)",
    bestFor: "High-contrast 2-color logos",
    description:
      "Palette=2 cleaning collapses every glyph to a single foreground color, then VTracer traces in binary mode. Eliminates inter-letter color drift and sub-pixel anti-aliasing fragments. Best for cleo-style brand marks with one foreground tone on one background tone.",
  },
  {
    value: "vtracer_smooth",
    selectLabel: "VTracer smooth (best for multi-color logos)",
    bestFor: "Logos, icons, brand marks",
    description:
      "Bilateral filter and k-means palette snap (palette=6) flatten JPEG and anti-aliasing noise, then VTracer traces with a smooth-curve grid tuned for fewer control points. Recommended for flat-color artwork and text-heavy logos with multiple tones.",
  },
  {
    value: "starvector",
    selectLabel: "StarVector (GPU, best for illustrations)",
    bestFor: "Illustrations, complex artwork",
    description:
      "A vision-language model writes SVG path markup directly from the image. Multiple stochastic samples are scored; the best becomes the output. Excels on global likeness for rich artwork but can produce uneven letter edges on text-heavy logos.",
  },
  {
    value: "vtracer",
    selectLabel: "VTracer (best for photos and gradients)",
    bestFor: "Photos, gradients, many colors",
    description:
      "Traces color regions without palette preprocessing, preserving photographic detail and smooth gradients. Auto-tune sweeps a parameter grid and keeps the highest-scoring result.",
  },
];

/** Candidates inside Auto mode, in run order. */
export const AUTO_ENGINES: Pick<EngineOption, "selectLabel" | "bestFor" | "description">[] = [
  {
    selectLabel: "StarVector",
    bestFor: "Illustrations, complex artwork",
    description:
      "Neural im2svg on the raw image. Contributes when a CUDA GPU is available.",
  },
  {
    selectLabel: "VTracer",
    bestFor: "Photos, gradients, many colors",
    description: "Classical tracing with logo- or photo-specific auto-tune grids.",
  },
  {
    selectLabel: "VTracer smooth",
    bestFor: "Logos, icons, brand marks",
    description:
      "Palette-quantized (6 colors), denoised input traced with the smooth-curve grid (skipped for photos).",
  },
  {
    selectLabel: "VTracer monochrome",
    bestFor: "2-color brand marks (cleo, etc.)",
    description:
      "Palette=2 binary trace, only runs when the image is detected as high-contrast monochrome. Produces a minimal-path SVG with one foreground / one background color.",
  },
];

export function engineOption(value: EngineChoice): EngineOption {
  return ENGINE_OPTIONS.find((o) => o.value === value) ?? ENGINE_OPTIONS[0];
}