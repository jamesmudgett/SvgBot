import type { EngineChoice } from "./api/client";

export type EngineOption = {
  value: EngineChoice;
  /** Short label for the &lt;select&gt; option */
  selectLabel: string;
  /** One line shown under the engine picker */
  hint: string;
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
    hint: "",
    bestFor: "Maximum accuracy when you can wait",
    description:
      "Generates one candidate from each engine, ranks them with DinoScore (and an LPIPS tiebreak on logos when scores are close), then refines the winner. Default choice: slowest but best when you are unsure which engine fits the image.",
  },
  {
    value: "vtracer_smooth",
    selectLabel: "VTracer smooth (best for logos)",
    hint: "Denoises and palette-quantizes before tracing for clean curves on flat fills and text.",
    bestFor: "Logos, icons, brand marks",
    description:
      "Bilateral filter and k-means palette snap flatten JPEG and anti-aliasing noise, then VTracer traces with a smooth-curve grid tuned for fewer control points. Recommended for flat-color artwork and text-heavy logos.",
  },
  {
    value: "starvector",
    selectLabel: "StarVector (GPU, best for illustrations)",
    hint: "Neural im2svg model. Needs a CUDA GPU. Strong on complex shapes; text logos may look choppy.",
    bestFor: "Illustrations, complex artwork",
    description:
      "A vision-language model writes SVG path markup directly from the image. Multiple stochastic samples are scored; the best becomes the output. Excels on global likeness for rich artwork but can produce uneven letter edges on text-heavy logos.",
  },
  {
    value: "vtracer",
    selectLabel: "VTracer (best for photos and gradients)",
    hint: "Classical color tracing on the raw image with auto-tuned parameters.",
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
      "Palette-quantized, denoised input traced with the smooth-curve grid (skipped for photos).",
  },
];

export function engineOption(value: EngineChoice): EngineOption {
  return ENGINE_OPTIONS.find((o) => o.value === value) ?? ENGINE_OPTIONS[0];
}