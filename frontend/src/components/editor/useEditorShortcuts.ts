import { useEffect, useState } from "react";

import type { EditorTool } from "./types";

interface Options {
  onToolChange: (tool: EditorTool) => void;
  /** Disabling lets the parent freeze shortcuts (e.g. while loading). */
  enabled?: boolean;
}

interface Result {
  /** True while the user is holding Space; the canvas treats any pointer
   * drag as a pan while this is true, regardless of the active tool. */
  panOverride: boolean;
}

/** Returns true when key events should be ignored because the user is
 * typing into a form control or contenteditable surface. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return false;
}

/**
 * Global keyboard shortcuts for the SVG editor.
 *
 * - `s` -> switch to Select.
 * - `m` -> switch to Marquee.
 * - Space (held) -> temporary pan override (the canvas reads
 *   `panOverride` from the returned value).
 *
 * Modifier-key combinations (Cmd/Ctrl/Alt/Shift) are deliberately
 * ignored so OS-level shortcuts like Cmd+S keep working. We also bail
 * when focus is inside an input / textarea / contenteditable so the
 * chat input doesn't get hijacked.
 */
export function useEditorShortcuts({
  onToolChange,
  enabled = true,
}: Options): Result {
  const [panOverride, setPanOverride] = useState(false);

  useEffect(() => {
    if (!enabled) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (isTypingTarget(event.target)) return;

      if (event.code === "Space") {
        event.preventDefault();
        setPanOverride(true);
        return;
      }

      if (event.shiftKey) return; // shift modifies select; not a tool switch
      if (event.repeat) return;

      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        onToolChange("select");
      } else if (key === "m") {
        event.preventDefault();
        onToolChange("marquee");
      }
    };

    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code === "Space") setPanOverride(false);
    };

    const onBlur = () => setPanOverride(false);

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, [onToolChange, enabled]);

  return { panOverride };
}
