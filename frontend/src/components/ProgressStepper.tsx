import type { EngineChoice, JobPhase, JobStatus } from "../api/client";

/** A single step rendered in the vertical progress list. */
interface Step {
  id: JobPhase;
  label: string;
  /** Hide unless the phase is actually active or just completed (e.g. "fetching" only when URL mode). */
  conditional?: boolean;
  /**
   * Engine-specific step: only show once the backend reports this phase
   * (or while it is the active phase). Auto mode does not always run every
   * engine (e.g. vtracer_mono only for logos, vtracer_smooth not for photos).
   */
  engineStep?: boolean;
}

const ALL_STEPS: Step[] = [
  { id: "fetching", label: "Downloading image", conditional: true },
  { id: "preprocessing", label: "Analyzing image" },
  { id: "starvector", label: "Generating with StarVector", engineStep: true },
  { id: "vtracer", label: "Tracing with VTracer", engineStep: true },
  { id: "vtracer_smooth", label: "Smoothing curves", engineStep: true },
  { id: "vtracer_mono", label: "Tracing 2-color logo", engineStep: true },
  { id: "refining", label: "Refining details" },
  { id: "sanitizing", label: "Cleaning up SVG" },
];

const PHASE_RANK = ALL_STEPS.reduce<Record<string, number>>((acc, step, idx) => {
  acc[step.id] = idx;
  return acc;
}, {});

function pickSteps(
  engine: EngineChoice,
  source: "file" | "url",
  phaseLog: Record<string, string> | undefined,
  currentPhase: JobPhase | undefined,
): Step[] {
  return ALL_STEPS.filter((s) => {
    if (s.id === "fetching") return source === "url";
    if (s.id === "starvector") return engine === "starvector";
    if (s.id === "vtracer") return engine === "vtracer";
    if (s.id === "vtracer_smooth") return engine === "vtracer_smooth";
    if (s.id === "vtracer_mono") return engine === "vtracer_mono";

    // Auto: only show engine steps the backend actually entered. The orchestrator
    // skips vtracer_mono for non-logos, vtracer_smooth for photos, starvector
    // when CUDA is unavailable, etc.
    if (engine === "auto" && s.engineStep) {
      return Boolean(phaseLog?.[s.id] || currentPhase === s.id);
    }

    return true;
  });
}

interface Props {
  job: JobStatus | null;
  engine: EngineChoice;
  source: "file" | "url";
  /** Whether the user has clicked "Convert" (controls whether we render at all). */
  active: boolean;
  /**
   * Sticky map of phase -> last message reported while that phase was active.
   * Used to keep showing per-engine score messages (e.g. "VTracer: dino=0.93
   * lpips=0.99") on completed steps after the active phase advances.
   */
  phaseLog?: Record<string, string>;
}

/**
 * Vertical step indicator showing what the backend is currently doing.
 *
 * - Steps before the current phase render with a check mark
 * - The current step gets a spinning indicator and bold label
 * - Future steps render as dim circles
 * - When the job fails, we keep completed steps but mark the failed step red
 */
export default function ProgressStepper({
  job,
  engine,
  source,
  active,
  phaseLog,
}: Props) {
  if (!active && !job) return null;

  const currentPhase: JobPhase | undefined = job?.phase;
  const steps = pickSteps(engine, source, phaseLog, currentPhase);
  const failed = job?.status === "failed";
  const completed = job?.status === "completed";

  const currentRank = currentPhase ? PHASE_RANK[currentPhase] ?? -1 : -1;

  const liveLabel = job?.progress || (active ? "Submitting…" : "");

  return (
    <div className="panel progress-panel" role="status" aria-live="polite">
      <div className="progress-header">
        <span className={`progress-pulse ${failed ? "failed" : completed ? "done" : ""}`} />
        <span className="progress-headline">
          {failed
            ? "Conversion failed"
            : completed
              ? `Conversion complete in ${formatMs(job?.result?.metrics.ms)}`
              : liveLabel || "Starting…"}
        </span>
      </div>

      <ol className="progress-steps">
        {steps.map((step) => {
          const rank = PHASE_RANK[step.id];
          let state: "done" | "active" | "pending" | "failed" = "pending";
          if (failed) {
            if (currentPhase === step.id) state = "failed";
            else if (rank < currentRank) state = "done";
          } else if (completed) {
            state = "done";
          } else if (currentPhase === step.id) {
            state = "active";
          } else if (rank < currentRank) {
            state = "done";
          }

          const detail =
            state === "active"
              ? liveLabel
              : (phaseLog?.[step.id] ?? "");
          const showDetail =
            (state === "done" || state === "active" || state === "failed") &&
            detail &&
            detail !== step.label;

          return (
            <li key={step.id} className={`progress-step progress-step-${state}`}>
              <span className="progress-step-icon" aria-hidden>
                {state === "done" && "✓"}
                {state === "active" && <span className="spinner" />}
                {state === "failed" && "!"}
                {state === "pending" && ""}
              </span>
              <div className="progress-step-text">
                <span className="progress-step-label">{step.label}</span>
                {showDetail && (
                  <span className="progress-step-detail">{detail}</span>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function formatMs(ms: number | undefined): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
