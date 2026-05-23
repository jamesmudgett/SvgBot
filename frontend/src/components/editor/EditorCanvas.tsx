import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  bboxIntersectsRect,
  parseSvg,
  type SvgRect,
} from "../../utils/svgDoc";
import type { EditorPrefs, EditorTool, ViewBox } from "./types";

/** Rectangle in user-space coordinates, used for marquee selection. */
type MarqueeRect = SvgRect;

interface Props {
  svg: string;
  selection: ReadonlySet<string>;
  tool: EditorTool;
  /** When true, treat the next pointer drag as a pan regardless of the
   * active tool. Driven by the Space-key shortcut handled in the parent. */
  panOverride?: boolean;
  view: ViewBox;
  prefs: EditorPrefs;
  originalImageUrl: string | null;
  /** Persistent rectangle the user lassoed in marquee mode. Shown as a
   * solid blue outline on top of the canvas so they remember what region
   * is currently snapshotted for Grok. */
  region: SvgRect | null;
  onSelectionChange: (ids: string[], replace: boolean) => void;
  onViewChange: (next: ViewBox) => void;
  onRegionChange: (rect: SvgRect | null) => void;
  /** Pixel size reporter so the parent can drive ruler tick math without
   * a second ResizeObserver elsewhere in the tree. */
  onCanvasSizeChange?: (size: { width: number; height: number }) => void;
}

export interface EditorCanvasHandle {
  /** Reset pan/zoom to fit the document view. */
  resetView: () => void;
  /** Fetch the current bbox for an element by id (in SVG user units). */
  getBBox: (id: string) => SvgRect | null;
}

const ZOOM_MIN = 0.1;
const ZOOM_MAX = 80;

/** Parse the SVG string and return the document's intrinsic viewBox.
 *
 * Falls back to an inferred viewBox when the document only has
 * width/height. We use this as the "home" viewBox for reset-zoom and
 * as the canvas's initial view.
 */
function readDocumentViewBox(svg: string): ViewBox {
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
    /* fall through */
  }
  return { x: 0, y: 0, w: 1024, h: 1024 };
}

/** Pull the SVG's child markup out so we can drop it into our own
 * outer <svg> via innerHTML. We keep the user's original viewBox in a
 * separate state slot so the toolbar can reset back to it later. */
function extractInner(svg: string): string {
  try {
    const doc = parseSvg(svg);
    const serializer = new XMLSerializer();
    return Array.from(doc.documentElement.childNodes)
      .map((child) => serializer.serializeToString(child))
      .join("");
  } catch {
    return "";
  }
}

const EditorCanvas = forwardRef<EditorCanvasHandle, Props>(function EditorCanvas(
  {
    svg,
    selection,
    tool,
    panOverride = false,
    view,
    prefs,
    originalImageUrl,
    region,
    onSelectionChange,
    onViewChange,
    onRegionChange,
    onCanvasSizeChange,
  },
  ref,
) {
  const stageRef = useRef<SVGSVGElement | null>(null);
  const contentRef = useRef<SVGGElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  const [marquee, setMarquee] = useState<MarqueeRect | null>(null);
  const [selectionBoxes, setSelectionBoxes] = useState<
    Array<{ id: string; rect: SvgRect }>
  >([]);

  const docViewBox = useMemo(() => readDocumentViewBox(svg), [svg]);
  const innerMarkup = useMemo(() => extractInner(svg), [svg]);

  // Mount the user's SVG markup into our content <g> via innerHTML.
  // React's normal child rendering doesn't preserve SVG namespaces from
  // a string; innerHTML on an SVG element does, and we own the wrapper.
  useEffect(() => {
    const node = contentRef.current;
    if (!node) return;
    node.innerHTML = innerMarkup;
  }, [innerMarkup]);

  // Report pixel size up to the parent (used to draw rulers in pixel space).
  useEffect(() => {
    const node = wrapRef.current;
    if (!node || !onCanvasSizeChange) return;
    const update = () => {
      const rect = node.getBoundingClientRect();
      onCanvasSizeChange({ width: rect.width, height: rect.height });
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(node);
    return () => ro.disconnect();
  }, [onCanvasSizeChange]);

  // -- pointer math ---------------------------------------------------------
  const screenToUser = useCallback((clientX: number, clientY: number) => {
    const stage = stageRef.current;
    if (!stage) return { x: 0, y: 0 };
    if (typeof stage.getScreenCTM !== "function") {
      return { x: 0, y: 0 };
    }
    const ctm = stage.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const inv = ctm.inverse();
    const point = stage.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const transformed = point.matrixTransform(inv);
    return { x: transformed.x, y: transformed.y };
  }, []);

  /**
   * Compute an element's bounding box in our outer-SVG user coordinate
   * system. We deliberately go through screen space because the user's
   * SVG can carry nested transforms (the residual-refinement overlay,
   * for example, ships paths under a `<g transform="matrix(...)">`).
   * `getBBox()` ignores those transforms and gives a misleading rect;
   * `getBoundingClientRect()` collapses them down for us.
   */
  const elementUserBBox = useCallback(
    (el: Element): SvgRect | null => {
      if (typeof (el as Element & { getBoundingClientRect?: () => DOMRect })
        .getBoundingClientRect !== "function") {
        return null;
      }
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return null;
      const tl = screenToUser(rect.left, rect.top);
      const br = screenToUser(rect.right, rect.bottom);
      return {
        x: Math.min(tl.x, br.x),
        y: Math.min(tl.y, br.y),
        width: Math.abs(br.x - tl.x),
        height: Math.abs(br.y - tl.y),
      };
    },
    [screenToUser],
  );

  // Recompute selection bboxes whenever the selection or the SVG changes.
  // jsdom doesn't implement getBoundingClientRect with real layout, so the
  // boxes will simply be empty there (which is fine for unit tests).
  useEffect(() => {
    const node = contentRef.current;
    if (!node) {
      setSelectionBoxes([]);
      return;
    }
    const out: Array<{ id: string; rect: SvgRect }> = [];
    selection.forEach((id) => {
      const el = node.querySelector(`[id="${cssEscape(id)}"]`);
      if (!el) return;
      const rect = elementUserBBox(el);
      if (rect) out.push({ id, rect });
    });
    setSelectionBoxes(out);
  }, [selection, innerMarkup, view, elementUserBBox]);

  useImperativeHandle(
    ref,
    () => ({
      resetView: () => onViewChange(docViewBox),
      getBBox: (id: string) => {
        const node = contentRef.current?.querySelector(
          `[id="${cssEscape(id)}"]`,
        );
        if (!node) return null;
        return elementUserBBox(node);
      },
    }),
    [docViewBox, onViewChange, elementUserBBox],
  );

  // -- wheel zoom -----------------------------------------------------------
  const onWheel = useCallback(
    (event: React.WheelEvent<HTMLDivElement>) => {
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0015);
      const cursor = screenToUser(event.clientX, event.clientY);
      const newW = Math.max(
        view.w / ZOOM_MAX,
        Math.min(view.w / ZOOM_MIN, view.w / factor),
      );
      const newH = newW * (view.h / view.w);
      const ratioX = (cursor.x - view.x) / view.w;
      const ratioY = (cursor.y - view.y) / view.h;
      onViewChange({
        x: cursor.x - ratioX * newW,
        y: cursor.y - ratioY * newH,
        w: newW,
        h: newH,
      });
    },
    [view, onViewChange, screenToUser],
  );

  // -- pan / marquee / click ------------------------------------------------
  const dragRef = useRef<
    | {
        kind: "pan";
        startX: number;
        startY: number;
        view0: ViewBox;
      }
    | {
        kind: "marquee";
        anchor: { x: number; y: number };
      }
    | null
  >(null);

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (
        event.button === 1 ||
        tool === "pan" ||
        panOverride ||
        event.altKey
      ) {
        dragRef.current = {
          kind: "pan",
          startX: event.clientX,
          startY: event.clientY,
          view0: view,
        };
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
        return;
      }
      if (event.button !== 0) return;

      // Click-select: find the nearest ancestor with an id within the SVG content.
      // Skip overlay layers and the persistent region rect (they have pointer-events
      // disabled in CSS so this is mostly a safety net).
      const target = event.target as Element | null;
      if (target && target instanceof Element && tool === "select") {
        const owner = target.closest("[id]") as Element | null;
        if (owner && contentRef.current?.contains(owner)) {
          const id = owner.getAttribute("id");
          if (id) {
            onSelectionChange([id], !event.shiftKey);
            return;
          }
        }
      }

      // Empty space click: in marquee mode, start a new region; in select mode,
      // clear current selection (and the persistent region) when no shift held.
      if (tool === "marquee" || tool === "select") {
        const start = screenToUser(event.clientX, event.clientY);
        if (tool === "select" && !event.shiftKey) {
          onSelectionChange([], true);
          if (region) onRegionChange(null);
        }
        dragRef.current = { kind: "marquee", anchor: start };
        setMarquee({ x: start.x, y: start.y, width: 0, height: 0 });
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
      }
    },
    [tool, panOverride, view, screenToUser, onSelectionChange, onRegionChange, region],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      if (drag.kind === "pan") {
        const stage = stageRef.current;
        if (!stage) return;
        const rect = stage.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        const dx = ((event.clientX - drag.startX) / rect.width) * drag.view0.w;
        const dy =
          ((event.clientY - drag.startY) / rect.height) * drag.view0.h;
        onViewChange({
          x: drag.view0.x - dx,
          y: drag.view0.y - dy,
          w: drag.view0.w,
          h: drag.view0.h,
        });
        return;
      }
      if (drag.kind === "marquee") {
        const cur = screenToUser(event.clientX, event.clientY);
        const x = Math.min(drag.anchor.x, cur.x);
        const y = Math.min(drag.anchor.y, cur.y);
        const width = Math.abs(cur.x - drag.anchor.x);
        const height = Math.abs(cur.y - drag.anchor.y);
        setMarquee({ x, y, width, height });
      }
    },
    [onViewChange, screenToUser],
  );

  const onPointerUp = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      dragRef.current = null;
      try {
        (event.currentTarget as HTMLElement).releasePointerCapture(
          event.pointerId,
        );
      } catch {
        /* pointer wasn't captured */
      }
      if (!drag) return;
      if (drag.kind === "marquee" && marquee) {
        if (marquee.width > 4e-3 && marquee.height > 4e-3) {
          // Persist the rectangle so Grok can act on the same region across
          // multiple chat turns and the user gets a visible reminder of it.
          if (tool === "marquee") onRegionChange(marquee);

          const node = contentRef.current;
          if (node) {
            const ids: string[] = [];
            node.querySelectorAll("[id]").forEach((el) => {
              const elRect = elementUserBBox(el);
              if (!elRect) return;
              if (bboxIntersectsRect(elRect, marquee)) {
                const id = el.getAttribute("id");
                if (id) ids.push(id);
              }
            });
            if (ids.length > 0 || tool === "marquee") {
              onSelectionChange(ids, !event.shiftKey);
            }
          }
        }
        setMarquee(null);
      }
    },
    [marquee, onSelectionChange, onRegionChange, tool, elementUserBBox],
  );

  const viewAttr = `${view.x} ${view.y} ${view.w} ${view.h}`;
  const overlayVisible = prefs.overlayOpacity > 0 && originalImageUrl;

  return (
    <div
      ref={wrapRef}
      className="editor-canvas"
      data-grid={prefs.showGrid ? "on" : "off"}
      data-tool={tool}
      data-pan-override={panOverride ? "on" : "off"}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      <svg
        ref={stageRef}
        className="editor-stage"
        viewBox={viewAttr}
        preserveAspectRatio="xMidYMid meet"
      >
        <g ref={contentRef} className="editor-content" />
        {overlayVisible && (
          <image
            href={originalImageUrl ?? undefined}
            x={docViewBox.x}
            y={docViewBox.y}
            width={docViewBox.w}
            height={docViewBox.h}
            opacity={prefs.overlayOpacity}
            preserveAspectRatio="xMidYMid meet"
            pointerEvents="none"
            className="editor-overlay-image"
          />
        )}
        <g className="editor-selection" pointerEvents="none">
          {selectionBoxes.map(({ id, rect }) => (
            <rect
              key={id}
              x={rect.x}
              y={rect.y}
              width={rect.width}
              height={rect.height}
              className="editor-selection-rect"
            />
          ))}
        </g>
        {region && (
          <rect
            className="editor-region"
            x={region.x}
            y={region.y}
            width={region.width}
            height={region.height}
            pointerEvents="none"
          />
        )}
        {marquee && (
          <rect
            className="editor-marquee"
            x={marquee.x}
            y={marquee.y}
            width={marquee.width}
            height={marquee.height}
            pointerEvents="none"
          />
        )}
      </svg>
    </div>
  );
});

/** Tiny CSS.escape polyfill so we can build attribute selectors safely. */
function cssEscape(value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/(["\\\]])/g, "\\$1");
}

export default EditorCanvas;
