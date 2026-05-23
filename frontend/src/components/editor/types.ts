export type EditorTool =
  | "select"
  | "marquee"
  | "pan"
  | "fill"
  | "stroke"
  | "delete";

export interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  /** Server-supplied SVG when this is an assistant message that proposes an edit. */
  pendingSvg?: string;
  /** True once the proposed edit has been applied to the canvas. */
  applied?: boolean;
  /** True when this assistant card represents an error (renders with the warning style). */
  isError?: boolean;
  modelMs?: number;
}

export interface EditorPrefs {
  showGrid: boolean;
  showRulers: boolean;
  overlayOpacity: number;
}
