export type QualityTier = "standard" | "high";
export type EngineChoice =
  | "auto"
  | "starvector"
  | "vtracer"
  | "vtracer_smooth"
  | "vtracer_mono";

/** Keep in sync with `backend/app/models/schemas.py::JobPhase`. */
export type JobPhase =
  | "queued"
  | "fetching"
  | "preprocessing"
  | "starvector"
  | "vtracer"
  | "vtracer_smooth"
  | "vtracer_mono"
  | "refining"
  | "smoothing"
  | "sanitizing"
  | "done"
  | "failed";

/** Which post-process smoothing method (if any) produced the final SVG. */
export type SmoothingMethod = "none" | "supersample" | "bezier_refit";

export interface CandidateScore {
  engine: string;
  dino: number;
  lpips: number;
  mean: number;
  selected: boolean;
  tried: number;
}

export interface JobMetrics {
  dino_score: number | null;
  lpips: number | null;
  engine: string;
  candidates_tried: number;
  path_count: number;
  ms: number;
  base_dino_score?: number | null;
  refine_passes?: number;
  refine_coverage?: number;
  candidate_scores?: CandidateScore[];
  decision?: string;
  smoothing_applied?: boolean;
  smoothing_method?: SmoothingMethod;
  smoothing_delta?: number;
}

export interface JobResult {
  svg: string;
  width: number;
  height: number;
  metrics: JobMetrics;
}

export interface JobStatus {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  phase?: JobPhase;
  progress: string;
  result?: JobResult;
  error?: string;
}

export type VectorizeSource = { kind: "file"; file: File } | { kind: "url"; url: string };

import { httpError, wrapFetchError, apiUrl } from "./errors";

export { API_BASE } from "./errors";

export async function checkHealth(): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(apiUrl("/health"), { signal: controller.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export async function createVectorizeJob(
  source: VectorizeSource,
  options: {
    quality: QualityTier;
    engine: EngineChoice;
    fontless: boolean;
  }
): Promise<string> {
  const form = new FormData();
  if (source.kind === "file") {
    form.append("file", source.file);
  } else {
    form.append("image_url", source.url);
  }
  form.append("quality", options.quality);
  form.append("engine", options.engine);
  form.append("fontless", String(options.fontless));

  let res: Response;
  try {
    res = await fetch(apiUrl("/api/vectorize"), {
      method: "POST",
      body: form,
    });
  } catch (err) {
    throw wrapFetchError(err, "upload");
  }

  if (!res.ok) {
    const text = await res.text();
    throw httpError(res.status, text, "upload");
  }
  const data = await res.json();
  return data.job_id as string;
}

export async function getJob(jobId: string): Promise<JobStatus> {
  let res: Response;
  try {
    res = await fetch(apiUrl(`/api/jobs/${jobId}`));
  } catch (err) {
    throw wrapFetchError(err, "poll");
  }
  if (!res.ok) {
    const text = await res.text();
    throw httpError(res.status, text, "poll");
  }
  return res.json();
}

export async function pollJob(
  jobId: string,
  onUpdate?: (job: JobStatus) => void,
  intervalMs = 800
): Promise<JobStatus> {
  for (;;) {
    const job = await getJob(jobId);
    onUpdate?.(job);
    if (job.status === "completed" || job.status === "failed") {
      return job;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export function svgDownloadUrl(jobId: string): string {
  return apiUrl(`/api/jobs/${jobId}/svg`);
}
