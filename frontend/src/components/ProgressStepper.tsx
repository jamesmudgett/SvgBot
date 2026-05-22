import type { EngineChoice, JobPhase, JobStatus } from "../api/client";

/** A single step rendered in the vertical progress list. */
interface Step {
  id: JobPhase;
  label: string;
  /** Hide unless the phase is actually active or just completed (e.g. "fetching" only when URL mode). */
  conditional?: boolean;
}

const ALL_STEPS: Step[] = [
  { id: "fetching", label: "Downloading image", conditional: true },
  { id: "preprocessing", label: "Analyzing image" },
  { id: "starvector", label: "Generating with StarVector" },
  { id: "vtracer", label: "Tracing with VTracer" },
  { id: "vtracer_smooth", label: "Smoothing curves" },
  { id: "refining", label: "Refining details" },
  { id: "sanitizing", label: "Cleaning up SVG" },
];

const PHASE_RANK = ALL_STEPS.reduce<Record<string, number>>((acc, step, idx) => {
  acc[step.id] = idx;
  return acc;
}, {});

function pickSteps(engine: EngineChoice, source: "file" | "url"): Step[] {
  return ALL_STEPS.filter((s) => {
    if (s.id === "fetching") return source === "url";
    if (s.id === "starvector") return engine === "auto" || engine === "starvector";
    if (s.id === "vtracer") return engine === "auto" || engine === "vtracer";
    if (s.id === "vtracer_smooth") return engine === "auto" || engine === "vtracer_smooth";
    return true;
  });
}

interface Props {
  job: JobStatus | null;
  engine: EngineChoice;
  source: "file" | "url";
  /** Whether the user has clicked "Convert" (controls whether we render at all). */
  active: boolean;
}

/**
 * Vertical step indicator showing what the backend is currently doing.
 *
 * - Steps before the current phase render with a check mark
 * - The current step gets a spinning indicator and bold label
 * - Future steps render as dim circles
 * - When the job fails, we keep completed steps but mark the failed step red
 */
export default function ProgressStepper({ job, engine, source, active }: Props) {
  if (!active && !job) return null;

  const steps = pickSteps(engine, source);
  const currentPhase: JobPhase | undefined = job?.phase;
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

          return (
            <li key={step.id} className={`progress-step progress-step-${state}`}>
              <span className="progress-step-icon" aria-hidden>
                {state === "done" && "✓"}
                {state === "active" && <span className="spinner" />}
                {state === "failed" && "!"}
                {state === "pending" && ""}
              </span>
              <span className="progress-step-label">{step.label}</span>
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
