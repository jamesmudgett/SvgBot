import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getJob,
  originalImageUrl,
  svgDownloadUrl,
  type JobStatus,
} from "../api/client";
import ChatDock from "../components/editor/ChatDock";
import EditorCanvas, {
  type EditorCanvasHandle,
} from "../components/editor/EditorCanvas";
import EditorToolbar from "../components/editor/EditorToolbar";
import Rulers from "../components/editor/Rulers";
import type { EditorPrefs, EditorTool, ViewBox } from "../components/editor/types";
import { useEditorShortcuts } from "../components/editor/useEditorShortcuts";
import {
  ensureIds,
  parseSvg,
  removeIds,
  serialize,
  setAttrs,
  type SvgRect,
} from "../utils/svgDoc";

const HISTORY_CAP = 50;

interface History {
  past: string[];
  future: string[];
}

/** Read the document's intrinsic viewBox so we know what "Reset zoom" returns to. */
function readDocViewBox(svg: string): ViewBox {
  try {
    const doc = parseSvg(svg);
    const root = doc.documentElement;
    const vb = root.getAttribute("viewBox");
    if (vb) {
      const parts = vb.trim().split(/[\s,]+/).map(Number);
      if (parts.length === 4 && parts.every((n) => Number.isFinite(n))) {
        return { x: parts[0], y: parts[1], w: parts[2], h: parts[3] };
      }
    }
    const w = parseFloat(root.getAttribute("width") || "0");
    const h = parseFloat(root.getAttribute("height") || "0");
    if (w > 0 && h > 0) return { x: 0, y: 0, w, h };
  } catch {
    /* ignore */
  }
  return { x: 0, y: 0, w: 1024, h: 1024 };
}

/** Run a mutation on a parsed copy of the current SVG and return the new
 * serialized string. We always go through this helper so the canonical
 * representation in state stays a string, which makes undo trivial. */
function mutate(svg: string, fn: (doc: Document) => void): string {
  const doc = parseSvg(svg);
  fn(doc);
  return serialize(doc);
}

export default function EditorPage() {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const canvasHandle = useRef<EditorCanvasHandle | null>(null);

  const [job, setJob] = useState<JobStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [svg, setSvg] = useState<string | null>(null);
  const [history, setHistory] = useState<History>({ past: [], future: [] });
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [region, setRegion] = useState<SvgRect | null>(null);
  const [tool, setTool] = useState<EditorTool>("select");
  const [view, setView] = useState<ViewBox>({ x: 0, y: 0, w: 1024, h: 1024 });
  const [prefs, setPrefs] = useState<EditorPrefs>({
    showGrid: true,
    showRulers: false,
    overlayOpacity: 0,
  });

  const docViewBox = useMemo(
    () => (svg ? readDocViewBox(svg) : { x: 0, y: 0, w: 1024, h: 1024 }),
    [svg],
  );

  // Keyboard shortcuts: s = select, m = marquee, space-held = pan override.
  // The hook bails on inputs/textareas so the chat dock stays unaffected.
  const { panOverride } = useEditorShortcuts({
    onToolChange: setTool,
    enabled: svg !== null,
  });

  // Initial fetch + ensure ids on the loaded SVG so the LLM has stable handles.
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    (async () => {
      try {
        const fetched = await getJob(jobId);
        if (cancelled) return;
        setJob(fetched);
        if (fetched.status === "failed") {
          setLoadError(fetched.error || "Job failed.");
          return;
        }
        if (fetched.result?.svg) {
          const idAssigned = mutate(fetched.result.svg, (doc) => {
            ensureIds(doc);
          });
          setSvg(idAssigned);
          const vb = readDocViewBox(idAssigned);
          setView(vb);
        } else if (fetched.status !== "completed") {
          setLoadError(
            "This job is still running. Wait for it to finish on the home page, then click Edit and Refine.",
          );
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  // Confirm before leaving when there are unsaved (unundoable) changes.
  useEffect(() => {
    if (history.past.length === 0) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [history.past.length]);

  const pushHistory = useCallback(
    (current: string, next: string) => {
      if (current === next) return next;
      setHistory((prev) => {
        const past = [...prev.past, current];
        if (past.length > HISTORY_CAP) past.shift();
        return { past, future: [] };
      });
      return next;
    },
    [],
  );

  const replaceSvg = useCallback(
    (next: string) => {
      setSvg((current) => {
        if (current === null) return next;
        pushHistory(current, next);
        return next;
      });
    },
    [pushHistory],
  );

  const undo = useCallback(() => {
    setHistory((prev) => {
      if (prev.past.length === 0) return prev;
      const past = [...prev.past];
      const last = past.pop()!;
      const future = [svg ?? "", ...prev.future];
      setSvg(last);
      return { past, future };
    });
  }, [svg]);

  const redo = useCallback(() => {
    setHistory((prev) => {
      if (prev.future.length === 0) return prev;
      const [next, ...rest] = prev.future;
      const past = [...prev.past, svg ?? ""];
      if (past.length > HISTORY_CAP) past.shift();
      setSvg(next);
      return { past, future: rest };
    });
  }, [svg]);

  const onSelectionChange = useCallback(
    (ids: string[], replace: boolean) => {
      setSelection((prev) => {
        if (replace) return new Set(ids);
        const next = new Set(prev);
        for (const id of ids) {
          if (next.has(id)) next.delete(id);
          else next.add(id);
        }
        return next;
      });
    },
    [],
  );

  const onPickColor = useCallback(
    (attr: "fill" | "stroke", color: string) => {
      if (!svg || selection.size === 0) return;
      const ids = Array.from(selection);
      const next = mutate(svg, (doc) => {
        setAttrs(doc, ids, { [attr]: color });
      });
      replaceSvg(next);
    },
    [svg, selection, replaceSvg],
  );

  const onDelete = useCallback(() => {
    if (!svg || selection.size === 0) return;
    const ids = Array.from(selection);
    const next = mutate(svg, (doc) => {
      removeIds(doc, ids);
    });
    setSelection(new Set());
    replaceSvg(next);
  }, [svg, selection, replaceSvg]);

  const onResetView = useCallback(() => {
    setView(docViewBox);
  }, [docViewBox]);

  const onApplyLlmEdit = useCallback(
    (newSvg: string, _summary: string) => {
      const idAssigned = mutate(newSvg, (doc) => {
        ensureIds(doc);
      });
      setSelection(new Set());
      setRegion(null);
      replaceSvg(idAssigned);
    },
    [replaceSvg],
  );

  const onDownload = useCallback(() => {
    if (!svg) return;
    const blob = new Blob([svg], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${jobId || "edited"}.svg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, [svg, jobId]);

  if (loadError) {
    return (
      <div className="editor-shell">
        <p className="error">{loadError}</p>
        <p>
          <button type="button" onClick={() => navigate("/")}>
            Back to home
          </button>
        </p>
      </div>
    );
  }

  if (!svg || !job) {
    return (
      <div className="editor-shell">
        <p className="progress">Loading editor...</p>
      </div>
    );
  }

  return (
    <div className="editor-shell">
      <EditorToolbar
        tool={tool}
        prefs={prefs}
        canUndo={history.past.length > 0}
        canRedo={history.future.length > 0}
        selectionCount={selection.size}
        hasRegion={region !== null}
        onToolChange={setTool}
        onPrefsChange={(next) => setPrefs((prev) => ({ ...prev, ...next }))}
        onUndo={undo}
        onRedo={redo}
        onResetView={onResetView}
        onDelete={onDelete}
        onClearRegion={() => setRegion(null)}
        onPickFill={(c) => onPickColor("fill", c)}
        onPickStroke={(c) => onPickColor("stroke", c)}
        onDownload={onDownload}
        onBack={() => navigate("/")}
      />

      <div className="editor-stage-wrap">
        <Rulers view={view} visible={prefs.showRulers} />
        <div
          className="editor-canvas-host"
          style={prefs.showRulers ? { paddingTop: 22, paddingLeft: 22 } : undefined}
        >
          <EditorCanvas
            ref={canvasHandle}
            svg={svg}
            selection={selection}
            tool={tool}
            panOverride={panOverride}
            view={view}
            prefs={prefs}
            originalImageUrl={originalImageUrl(jobId)}
            region={region}
            onSelectionChange={onSelectionChange}
            onViewChange={setView}
            onRegionChange={setRegion}
          />
        </div>
      </div>

      <ChatDock
        jobId={jobId}
        svg={svg}
        selectedIds={Array.from(selection)}
        region={region}
        onApply={onApplyLlmEdit}
      />

      <p className="editor-source-link">
        Server copy:{" "}
        <a href={svgDownloadUrl(jobId)} download={`${jobId}.svg`}>
          download original (pre-edit) SVG
        </a>
      </p>
    </div>
  );
}
