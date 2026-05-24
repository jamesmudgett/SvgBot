import { useCallback, useEffect, useRef, useState } from "react";
import {
  checkHealth,
  createVectorizeJob,
  pollJob,
  svgDownloadUrl,
  type EngineChoice,
  type JobStatus,
  type QualityTier,
  type SmoothingMethod,
  type VectorizeSource,
} from "../api/client";
import InfoSections from "../components/InfoSections";
import { DEFAULT_ENGINE, ENGINE_OPTIONS } from "../engineOptions";
import BeforeAfterCompare from "../components/BeforeAfterCompare";
import ExpandablePreview from "../components/ExpandablePreview";
import ProgressStepper from "../components/ProgressStepper";
import SvgPreview from "../components/SvgPreview";
import { fitContain } from "../utils/fitContain";

type SourceMode = "file" | "url";

function formatSmoothingMethod(method: SmoothingMethod): string {
  switch (method) {
    case "supersample":
      return "supersample retrace";
    case "bezier_refit":
      return "Bezier refit";
    default:
      return method;
  }
}

function formatSignedDelta(delta: number): string {
  const sign = delta >= 0 ? "+" : "";
  return `${sign}${delta.toFixed(3)}`;
}

function loadImageSize(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read image dimensions"));
    };
    img.src = url;
  });
}

function loadImageSizeFromUrl(
  url: string
): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () =>
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => reject(new Error("Could not load image from URL"));
    img.src = url;
  });
}

export default function HomePage() {
  const [sourceMode, setSourceMode] = useState<SourceMode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewSource, setPreviewSource] = useState<SourceMode>("file");
  const [inputSize, setInputSize] = useState<{ width: number; height: number } | null>(null);
  /** On-screen size of the original preview — vector preview uses the same dimensions. */
  const [displaySize, setDisplaySize] = useState<{ width: number; height: number } | null>(
    null
  );
  const uploadBoxRef = useRef<HTMLDivElement>(null);
  const uploadImgRef = useRef<HTMLImageElement>(null);
  const [quality, setQuality] = useState<QualityTier>("standard");
  const [engine, setEngine] = useState<EngineChoice>(DEFAULT_ENGINE);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobStatus | null>(null);
  /** Sticky map of phase -> last progress message seen for that phase. Lets the
   * stepper show the per-engine score on each completed step even after the
   * active phase advances. */
  const [phaseLog, setPhaseLog] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      for (let i = 0; i < 4 && !cancelled; i++) {
        if (await checkHealth()) {
          if (!cancelled) setBackendOk(true);
          return;
        }
        await new Promise((r) => setTimeout(r, 750));
      }
      if (!cancelled) setBackendOk(false);
    };
    void probe();
    return () => {
      cancelled = true;
    };
  }, []);

  const onFile = useCallback((f: File) => {
    setFile(f);
    setImageUrl("");
    setJob(null);
    setError(null);
    setInputSize(null);
    setDisplaySize(null);
    setPreviewSource("file");
    const url = URL.createObjectURL(f);
    setPreviewUrl((prev) => {
      if (prev && previewSourceWasObjectUrl(prev)) URL.revokeObjectURL(prev);
      return url;
    });
    void loadImageSize(f)
      .then(setInputSize)
      .catch(() => setInputSize(null));
  }, []);

  const onUrlChange = useCallback((url: string) => {
    setImageUrl(url);
    setError(null);
    if (!url) {
      setPreviewUrl((prev) => {
        if (prev && previewSourceWasObjectUrl(prev)) URL.revokeObjectURL(prev);
        return null;
      });
      setInputSize(null);
      setDisplaySize(null);
      return;
    }
  }, []);

  const onUrlBlur = useCallback(() => {
    if (!imageUrl) return;
    setFile(null);
    setJob(null);
    setError(null);
    setInputSize(null);
    setDisplaySize(null);
    setPreviewSource("url");
    setPreviewUrl((prev) => {
      if (prev && previewSourceWasObjectUrl(prev)) URL.revokeObjectURL(prev);
      return imageUrl;
    });
    void loadImageSizeFromUrl(imageUrl)
      .then(setInputSize)
      .catch(() => setInputSize(null));
  }, [imageUrl]);

  const measureDisplaySize = useCallback(() => {
    const img = uploadImgRef.current;
    if (img?.complete && img.naturalWidth > 0) {
      const rect = img.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setDisplaySize({
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        });
        return;
      }
    }
    const box = uploadBoxRef.current;
    if (box && inputSize) {
      const pad = 16;
      const fitted = fitContain(
        inputSize.width,
        inputSize.height,
        box.clientWidth - pad,
        Math.min(box.clientHeight - pad, 340)
      );
      if (fitted.width > 0) setDisplaySize(fitted);
    }
  }, [inputSize]);

  useEffect(() => {
    const box = uploadBoxRef.current;
    if (!previewUrl || !box) return;

    const ro = new ResizeObserver(() => measureDisplaySize());
    ro.observe(box);
    const img = uploadImgRef.current;
    if (img) {
      ro.observe(img);
      img.addEventListener("load", measureDisplaySize);
      if (img.complete) measureDisplaySize();
    }

    return () => {
      ro.disconnect();
      img?.removeEventListener("load", measureDisplaySize);
    };
  }, [previewUrl, inputSize, measureDisplaySize]);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const f = e.dataTransfer.files[0];
      if (f?.type.startsWith("image/")) onFile(f);
    },
    [onFile]
  );

  const canSubmit =
    !busy && (sourceMode === "file" ? !!file : imageUrl.trim().length > 0);

  const run = async () => {
    if (busy) return;
    let source: VectorizeSource | null = null;
    if (sourceMode === "file" && file) {
      source = { kind: "file", file };
    } else if (sourceMode === "url" && imageUrl.trim()) {
      source = { kind: "url", url: imageUrl.trim() };
    }
    if (!source) return;

    setBusy(true);
    setError(null);
    setPhaseLog({});
    setJob({
      job_id: "",
      status: "queued",
      phase: "queued",
      progress: "Submitting…",
    });

    try {
      const jobId = await createVectorizeJob(source, {
        quality,
        engine,
        fontless: true,
      });
      const result = await pollJob(jobId, (j) => {
        setJob(j);
        if (j.phase && j.progress) {
          setPhaseLog((prev) => ({ ...prev, [j.phase as string]: j.progress }));
        }
      });
      setJob(result);
      if (result.status === "failed") {
        setError(result.error ?? "Vectorization failed");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setJob(null);
    } finally {
      setBusy(false);
    }
  };

  const resultSvg =
    job?.status === "completed" && job.result ? job.result.svg : null;

  useEffect(() => {
    if (resultSvg) measureDisplaySize();
  }, [resultSvg, measureDisplaySize]);

  return (
    <>
      <header className="site-header">
        <img
          src="/assets/SvgBot.png"
          alt="SvgBot"
          className="site-logo"
        />
        <div className="site-header-text">
          <h1>SvgBot</h1>
          <p className="subtitle">
            <strong>The most accurate image → fontless SVG converter available!</strong> Not by picking
            one tracer and hoping for the best, but by running multiple vectorization engines in
            parallel, scoring every candidate with perceptual metrics, and iteratively diffing,
            patching, and merging corrective paths until fidelity plateaus.
          </p>
          <p className="subtitle subtitle-secondary">
            SvgBot combines StarVector (neural im2svg, GPU), VTracer (classical color tracing), DinoScore
            / LPIPS candidate ranking, and a residual-overlay refinement loop on every conversion that
            surgically fixes whatever the base engine missed.
          </p>
        </div>
      </header>

      {backendOk === false && (
        <p className="error">
          Backend is not reachable. Start the API on port 8000 (./run.sh or uvicorn), then refresh.
        </p>
      )}

      <div className="panel source-panel">
        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={sourceMode === "file"}
            className={`tab ${sourceMode === "file" ? "active" : ""}`}
            onClick={() => setSourceMode("file")}
          >
            Upload
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={sourceMode === "url"}
            className={`tab ${sourceMode === "url" ? "active" : ""}`}
            onClick={() => setSourceMode("url")}
          >
            From URL
          </button>
        </div>

        {sourceMode === "file" ? (
          <div
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
          >
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onFile(f);
              }}
            />
            {file ? file.name : "Drop an image or click to browse"}
          </div>
        ) : (
          <div className="url-input-wrap">
            <input
              type="url"
              className="url-input"
              placeholder="https://example.com/logo.png"
              value={imageUrl}
              onChange={(e) => onUrlChange(e.target.value)}
              onBlur={onUrlBlur}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  onUrlBlur();
                }
              }}
            />
            <p className="url-hint">
              Paste a direct link to a PNG, JPG, WebP, or GIF image.
            </p>
          </div>
        )}
      </div>

      <div className="panel controls">
        <label>
          Quality
          <select
            value={quality}
            onChange={(e) => setQuality(e.target.value as QualityTier)}
          >
            <option value="standard">Faster (8 refine passes, fewer candidates)</option>
            <option value="high">High (25 refine passes, more candidates)</option>
          </select>
        </label>
        <label className="engine-field">
          Engine
          <select
            value={engine}
            onChange={(e) => setEngine(e.target.value as EngineChoice)}
          >
            {ENGINE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.selectLabel}
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={!canSubmit} onClick={run}>
          {busy ? "Converting…" : "Convert to SVG"}
        </button>
      </div>

      <ProgressStepper
        job={job}
        engine={engine}
        source={previewSource}
        active={busy}
        phaseLog={phaseLog}
      />

      {error && <p className="error">{error}</p>}

      {job?.status === "completed" && job.result && (
        <div className="panel">
          <div className="metrics">
            <span>
              DinoScore: <strong>{job.result.metrics.dino_score?.toFixed(3) ?? "—"}</strong>
            </span>
            {job.result.metrics.base_dino_score != null &&
              job.result.metrics.refine_passes != null &&
              job.result.metrics.refine_passes > 0 && (
                <span>
                  Base score:{" "}
                  <strong>{job.result.metrics.base_dino_score.toFixed(3)}</strong>
                </span>
              )}
            <span>
              LPIPS: <strong>{job.result.metrics.lpips?.toFixed(3) ?? "—"}</strong>
            </span>
            <span>
              Engine: <strong>{job.result.metrics.engine}</strong>
            </span>
            <span>
              Paths: <strong>{job.result.metrics.path_count}</strong>
            </span>
            {job.result.metrics.refine_passes != null &&
              job.result.metrics.refine_passes > 0 && (
                <span>
                  Refine passes:{" "}
                  <strong>{job.result.metrics.refine_passes}</strong>
                </span>
              )}
            {job.result.metrics.refine_coverage != null &&
              job.result.metrics.refine_coverage > 0 && (
                <span>
                  Patched:{" "}
                  <strong>
                    {(job.result.metrics.refine_coverage * 100).toFixed(1)}%
                  </strong>
                </span>
              )}
            <span>
              Time: <strong>{job.result.metrics.ms} ms</strong>
            </span>
          </div>
          {job.result.metrics.decision && (
            <p className="decision-banner">{job.result.metrics.decision}</p>
          )}
          {job.result.metrics.smoothing_method !== undefined && (
            <p className="smoothing-banner">
              {job.result.metrics.smoothing_applied
                ? `Smoothing: applied via ${formatSmoothingMethod(
                    job.result.metrics.smoothing_method,
                  )}${
                    job.result.metrics.smoothing_delta !== undefined
                      ? ` (Δdino ${formatSignedDelta(
                          job.result.metrics.smoothing_delta,
                        )})`
                      : ""
                  }`
                : "Smoothing: skipped (no method improved the SVG)"}
            </p>
          )}
          {job.result.metrics.candidate_scores &&
            job.result.metrics.candidate_scores.length > 0 && (
              <details className="candidate-breakdown">
                <summary>
                  Per-engine scores ({job.result.metrics.candidate_scores.length})
                </summary>
                <div className="candidate-table-scroll">
                  <table className="candidate-table">
                    <thead>
                      <tr>
                        <th>Engine</th>
                        <th>DinoScore</th>
                        <th>LPIPS</th>
                        <th>Mean</th>
                        <th>Tried</th>
                        <th>Picked</th>
                      </tr>
                    </thead>
                    <tbody>
                      {job.result.metrics.candidate_scores.map((c) => (
                        <tr
                          key={c.engine}
                          className={c.selected ? "candidate-row-winner" : undefined}
                        >
                          <td>{c.engine}</td>
                          <td>{c.dino.toFixed(3)}</td>
                          <td>{c.lpips.toFixed(3)}</td>
                          <td>{c.mean.toFixed(3)}</td>
                          <td>{c.tried}</td>
                          <td>{c.selected ? "yes" : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          <div className="download-row">
            <a
              className="download-btn"
              href={svgDownloadUrl(job.job_id)}
              download={`${job.job_id}.svg`}
            >
              <svg
                className="download-btn-icon"
                viewBox="0 0 24 24"
                width="18"
                height="18"
                aria-hidden
              >
                <path
                  d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span>Download SVG</span>
              <span className="download-btn-meta">
                {(job.result.svg.length / 1024).toFixed(1)} KB
              </span>
            </a>
          </div>
        </div>
      )}

      <div className="preview-grid">
        <div className="panel">
          <h3>Original</h3>
          <div ref={uploadBoxRef} className="preview-box preview-box-upload">
            {previewUrl ? (
              <ExpandablePreview
                label="Original preview"
                frameStyle={
                  displaySize
                    ? {
                        width: displaySize.width,
                        height: displaySize.height,
                      }
                    : undefined
                }
                lightbox={
                  <img
                    className="preview-lightbox-media"
                    src={previewUrl}
                    alt="Original"
                    crossOrigin={previewSource === "url" ? "anonymous" : undefined}
                  />
                }
              >
                <img
                  ref={uploadImgRef}
                  className="preview-media"
                  src={previewUrl}
                  alt="Original"
                  crossOrigin={previewSource === "url" ? "anonymous" : undefined}
                />
              </ExpandablePreview>
            ) : (
              <span className="preview-placeholder">No image</span>
            )}
          </div>
        </div>
        <div className="panel">
          <h3>Vector</h3>
          <div className="preview-box preview-box-upload preview-box-vector">
            {resultSvg ? (
              <ExpandablePreview
                label="Before and after comparison"
                interactive={Boolean(previewUrl)}
                frameStyle={
                  displaySize
                    ? {
                        width: displaySize.width,
                        height: displaySize.height,
                      }
                    : undefined
                }
                lightbox={
                  previewUrl ? (
                    <BeforeAfterCompare
                      beforeSrc={previewUrl}
                      beforeCrossOrigin={
                        previewSource === "url" ? "anonymous" : undefined
                      }
                      afterSvg={resultSvg}
                    />
                  ) : (
                    <SvgPreview svg={resultSvg} className="preview-lightbox-media" />
                  )
                }
              >
                <SvgPreview svg={resultSvg} />
              </ExpandablePreview>
            ) : (
              <span className="preview-placeholder">—</span>
            )}
          </div>
        </div>
      </div>

      <InfoSections />
    </>
  );
}

function previewSourceWasObjectUrl(url: string): boolean {
  return url.startsWith("blob:");
}
