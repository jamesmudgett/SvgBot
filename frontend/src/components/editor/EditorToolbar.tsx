import type { ChangeEvent } from "react";

import type { EditorPrefs, EditorTool } from "./types";

interface Props {
  tool: EditorTool;
  prefs: EditorPrefs;
  canUndo: boolean;
  canRedo: boolean;
  selectionCount: number;
  hasRegion: boolean;
  onToolChange: (tool: EditorTool) => void;
  onPrefsChange: (next: Partial<EditorPrefs>) => void;
  onUndo: () => void;
  onRedo: () => void;
  onResetView: () => void;
  onDelete: () => void;
  onClearRegion: () => void;
  onPickFill: (color: string) => void;
  onPickStroke: (color: string) => void;
  onDownload: () => void;
  onBack: () => void;
}

interface ToolDef {
  id: EditorTool;
  label: string;
  /** Single-character or short shortcut shown in the tooltip. */
  shortcut: string;
  /** Renders the tool's glyph inside a 24x24 viewBox. */
  Icon: () => JSX.Element;
}

const TOOLS: ToolDef[] = [
  {
    id: "select",
    label: "Select",
    shortcut: "S",
    Icon: () => (
      <path d="M3 3l8 16 2-7 7-2L3 3z" />
    ),
  },
  {
    id: "marquee",
    label: "Marquee",
    shortcut: "M",
    Icon: () => (
      <rect
        x="3"
        y="3"
        width="18"
        height="18"
        rx="1"
        strokeDasharray="3 2"
      />
    ),
  },
  {
    id: "pan",
    label: "Pan",
    shortcut: "Hold Space + drag",
    Icon: () => (
      <g>
        <path d="M12 2v20" />
        <path d="M2 12h20" />
        <path d="M9 5l3-3 3 3" />
        <path d="M9 19l3 3 3-3" />
        <path d="M5 9l-3 3 3 3" />
        <path d="M19 9l3 3-3 3" />
      </g>
    ),
  },
];

export default function EditorToolbar({
  tool,
  prefs,
  canUndo,
  canRedo,
  selectionCount,
  hasRegion,
  onToolChange,
  onPrefsChange,
  onUndo,
  onRedo,
  onResetView,
  onDelete,
  onClearRegion,
  onPickFill,
  onPickStroke,
  onDownload,
  onBack,
}: Props) {
  return (
    <div className="editor-toolbar">
      <button
        type="button"
        className="editor-back-btn"
        onClick={onBack}
        title="Back to home"
      >
        Back
      </button>

      <div className="editor-tool-group" role="toolbar" aria-label="Tools">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`editor-tool editor-tool-icon ${tool === t.id ? "active" : ""}`}
            onClick={() => onToolChange(t.id)}
            title={`${t.label} (${t.shortcut})`}
            aria-label={t.label}
            aria-keyshortcuts={t.shortcut}
            aria-pressed={tool === t.id}
          >
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              aria-hidden
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <t.Icon />
            </svg>
          </button>
        ))}
      </div>

      <div className="editor-tool-group">
        <label className="editor-color-field">
          Fill
          <input
            type="color"
            aria-label="Fill color"
            onInput={(event: ChangeEvent<HTMLInputElement>) =>
              onPickFill(event.target.value)
            }
            disabled={selectionCount === 0}
          />
        </label>
        <label className="editor-color-field">
          Stroke
          <input
            type="color"
            aria-label="Stroke color"
            onInput={(event: ChangeEvent<HTMLInputElement>) =>
              onPickStroke(event.target.value)
            }
            disabled={selectionCount === 0}
          />
        </label>
        <button
          type="button"
          className="editor-tool"
          onClick={onDelete}
          disabled={selectionCount === 0}
          aria-label="Delete selection"
        >
          Delete
        </button>
        <span className="editor-selection-count">
          {selectionCount} selected
        </span>
        {hasRegion && (
          <button
            type="button"
            className="editor-region-chip"
            onClick={onClearRegion}
            aria-label="Clear region"
            title="Clear the marquee region snapshot"
          >
            <span className="editor-region-dot" /> Region snapshot
            <span className="editor-region-x">x</span>
          </button>
        )}
      </div>

      <div className="editor-tool-group">
        <button
          type="button"
          className="editor-tool"
          onClick={onUndo}
          disabled={!canUndo}
          aria-label="Undo"
        >
          Undo
        </button>
        <button
          type="button"
          className="editor-tool"
          onClick={onRedo}
          disabled={!canRedo}
          aria-label="Redo"
        >
          Redo
        </button>
        <button
          type="button"
          className="editor-tool"
          onClick={onResetView}
          aria-label="Reset zoom"
        >
          Reset zoom
        </button>
      </div>

      <div className="editor-tool-group">
        <button
          type="button"
          className={`editor-tool ${prefs.showGrid ? "active" : ""}`}
          onClick={() => onPrefsChange({ showGrid: !prefs.showGrid })}
          aria-label="Toggle grid"
          aria-pressed={prefs.showGrid}
        >
          Grid
        </button>
        <button
          type="button"
          className={`editor-tool ${prefs.showRulers ? "active" : ""}`}
          onClick={() => onPrefsChange({ showRulers: !prefs.showRulers })}
          aria-label="Toggle rulers"
          aria-pressed={prefs.showRulers}
        >
          Rulers
        </button>
        <label className="editor-overlay-field">
          <span>
            Overlay original (alpha {Math.round(prefs.overlayOpacity * 100)}%)
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={prefs.overlayOpacity}
            aria-label="Overlay original (alpha 0-100%)"
            onChange={(event) =>
              onPrefsChange({ overlayOpacity: parseFloat(event.target.value) })
            }
          />
        </label>
      </div>

      <div className="editor-tool-group editor-toolbar-end">
        <button
          type="button"
          className="editor-download-btn"
          onClick={onDownload}
          aria-label="Download SVG"
        >
          Download
        </button>
      </div>
    </div>
  );
}
