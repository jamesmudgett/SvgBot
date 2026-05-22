export type QualityTier = "standard" | "high";
export type EngineChoice = "auto" | "starvector" | "vtracer" | "vtracer_smooth";

/** Keep in sync with `backend/app/models/schemas.py::JobPhase`. */
export type JobPhase =
  | "queued"
  | "fetching"
  | "preprocessing"
  | "starvector"
  | "vtracer"
  | "vtracer_smooth"
  | "refining"
  | "sanitizing"
  | "done"
  | "failed";

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

/** Empty = Vite dev proxy. Set VITE_API_BASE=http://127.0.0.1:8000 to call API directly. */
export const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export function apiUrl(path: string): string {
  const base = API_BASE.replace(/\/$/, "");
  return `${base}${path}`;
}

function wrapFetchError(err: unknown, context: string): Error {
  if (err instanceof TypeError && /fetch|network/i.test(err.message)) {
    const hint = API_BASE
      ? API_BASE
      : "http://127.0.0.1:8000 (via Vite proxy when using npm run dev)";
    return new Error(
      `Cannot reach the API (${context}). Is the backend running at ${hint}? ` +
        "Start it with ./run.sh or: cd backend && uvicorn app.main:app --reload --port 8000"
    );
  }
  return err instanceof Error ? err : new Error(String(err));
}

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
    throw wrapFetchError(err, source.kind === "file" ? "upload" : "URL submit");
  }

  if (!res.ok) {
    const text = await res.text();
    try {
      const body = JSON.parse(text) as { detail?: string };
      if (body.detail) {
        throw new Error(body.detail);
      }
    } catch (e) {
      if (e instanceof Error && e.message !== text) {
        throw e;
      }
    }
    throw new Error(text || `Submit failed (${res.status})`);
  }
  const data = await res.json();
  return data.job_id as string;
}

export async function getJob(jobId: string): Promise<JobStatus> {
  let res: Response;
  try {
    res = await fetch(apiUrl(`/api/jobs/${jobId}`));
  } catch (err) {
    throw wrapFetchError(err, "job status");
  }
  if (!res.ok) throw new Error(`Job fetch failed (${res.status})`);
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
