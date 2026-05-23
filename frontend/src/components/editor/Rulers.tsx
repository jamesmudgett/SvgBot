import { useEffect, useRef, useState } from "react";

import type { ViewBox } from "./types";

interface Props {
  view: ViewBox;
  visible: boolean;
}

const RULER_PX = 22;

/** Pick a tick step that draws somewhere between 60 and 200 pixels apart at
 * the current zoom. We pick from a 1-2-5 base so labels stay round. */
function chooseStep(unitsPerPixel: number): number {
  if (!Number.isFinite(unitsPerPixel) || unitsPerPixel <= 0) return 10;
  const targetUnits = unitsPerPixel * 80;
  const pow = Math.pow(10, Math.floor(Math.log10(Math.max(targetUnits, 1e-6))));
  const candidates = [1, 2, 5, 10].map((m) => m * pow);
  for (const step of candidates) {
    if (step >= targetUnits) return step;
  }
  return candidates[candidates.length - 1];
}

function generateTicks(start: number, end: number, step: number): number[] {
  if (!Number.isFinite(step) || step <= 0) return [];
  const first = Math.ceil(start / step) * step;
  const out: number[] = [];
  for (let v = first; v <= end; v += step) {
    if (out.length > 200) break;
    out.push(parseFloat(v.toFixed(4)));
  }
  return out;
}

/** Top + left rulers for the editor canvas. Tick positions are computed in
 * CSS pixel space against the actual on-screen size of each strip; that
 * keeps labels readable regardless of how skinny or wide the canvas is. */
export default function Rulers({ view, visible }: Props) {
  if (!visible) return null;

  return (
    <>
      <HRuler view={view} />
      <VRuler view={view} />
      <div
        className="editor-ruler-corner"
        style={{ width: RULER_PX, height: RULER_PX }}
      />
    </>
  );
}

function HRuler({ view }: { view: ViewBox }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [pixelWidth, setPixelWidth] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => setPixelWidth(node.getBoundingClientRect().width);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  const step = chooseStep(view.w / Math.max(pixelWidth || 800, 1));
  const ticks = generateTicks(view.x, view.x + view.w, step);

  return (
    <div
      ref={ref}
      className="editor-ruler editor-ruler-h"
      style={{ height: RULER_PX, left: RULER_PX }}
    >
      {ticks.map((t) => {
        const px = ((t - view.x) / view.w) * pixelWidth;
        if (px < 0 || px > pixelWidth) return null;
        return (
          <div
            key={t}
            className="editor-ruler-tick-h"
            style={{ left: px }}
          >
            <span className="editor-ruler-label">{Math.round(t)}</span>
          </div>
        );
      })}
    </div>
  );
}

function VRuler({ view }: { view: ViewBox }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [pixelHeight, setPixelHeight] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => setPixelHeight(node.getBoundingClientRect().height);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  const step = chooseStep(view.h / Math.max(pixelHeight || 600, 1));
  const ticks = generateTicks(view.y, view.y + view.h, step);

  return (
    <div
      ref={ref}
      className="editor-ruler editor-ruler-v"
      style={{ width: RULER_PX, top: RULER_PX }}
    >
      {ticks.map((t) => {
        const py = ((t - view.y) / view.h) * pixelHeight;
        if (py < 0 || py > pixelHeight) return null;
        return (
          <div
            key={t}
            className="editor-ruler-tick-v"
            style={{ top: py }}
          >
            <span className="editor-ruler-label">{Math.round(t)}</span>
          </div>
        );
      })}
    </div>
  );
}
