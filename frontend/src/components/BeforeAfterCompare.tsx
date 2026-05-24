import { useCallback, useEffect, useRef, useState } from "react";
import SvgPreview from "./SvgPreview";

type Props = {
  beforeSrc: string;
  beforeCrossOrigin?: "anonymous";
  afterSvg: string;
};

export default function BeforeAfterCompare({
  beforeSrc,
  beforeCrossOrigin,
  afterSvg,
}: Props) {
  const [position, setPosition] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  const updatePosition = useCallback((clientX: number) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    if (rect.width <= 0) return;
    const x = Math.min(Math.max(clientX - rect.left, 0), rect.width);
    setPosition((x / rect.width) * 100);
  }, []);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      if (!draggingRef.current) return;
      updatePosition(event.clientX);
    };

    const stopDragging = () => {
      draggingRef.current = false;
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [updatePosition]);

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    updatePosition(event.clientX);
  };

  return (
    <div
      ref={containerRef}
      className="before-after"
      onPointerDown={onPointerDown}
      onClick={(event) => event.stopPropagation()}
      role="slider"
      aria-label="Compare original and vector preview"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(position)}
    >
      <img
        className="before-after-media"
        src={beforeSrc}
        alt="Original"
        crossOrigin={beforeCrossOrigin}
        draggable={false}
      />
      <div
        className="before-after-after"
        style={{ clipPath: `inset(0 0 0 ${position}%)` }}
      >
        <SvgPreview svg={afterSvg} className="before-after-media" />
      </div>
      <div className="before-after-divider" style={{ left: `${position}%` }}>
        <span className="before-after-handle" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="16" height="16">
            <path
              d="M10 8l-4 4 4 4M14 8l4 4-4 4"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </div>
      <span className="before-after-label before-after-label-before">Original</span>
      <span className="before-after-label before-after-label-after">Vector</span>
    </div>
  );
}
