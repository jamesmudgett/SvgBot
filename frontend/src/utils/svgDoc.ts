/** Parse, mutate, and stringify SVG documents for the editor.
 *
 * The editor keeps the source of truth as a serialized SVG string and
 * re-parses on every undo/redo or LLM apply. These helpers are pure
 * functions over that representation so they're cheap to unit test in
 * jsdom without mounting React.
 *
 * In production, `DOMParser` and `XMLSerializer` come from the browser.
 * Vitest runs them under jsdom, which provides both.
 */

export type SvgRect = { x: number; y: number; width: number; height: number };

const SVG_NS = "http://www.w3.org/2000/svg";

/** Tags whose visible geometry users typically want to select and edit. */
const DRAWABLE_TAGS = new Set([
  "path",
  "rect",
  "circle",
  "ellipse",
  "line",
  "polyline",
  "polygon",
  "text",
  "g",
]);

export function parseSvg(svg: string): Document {
  const trimmed = svg.trim();
  if (!trimmed) {
    throw new SvgParseError("Empty SVG document.");
  }
  const parser = new DOMParser();
  const doc = parser.parseFromString(trimmed, "image/svg+xml");
  // Browsers / jsdom both surface parse errors as a <parsererror> element.
  const errorNode = doc.getElementsByTagName("parsererror")[0];
  if (errorNode) {
    throw new SvgParseError(
      `Could not parse SVG: ${errorNode.textContent || "unknown XML error"}`,
    );
  }
  const root = doc.documentElement;
  if (!root || root.tagName.toLowerCase() !== "svg") {
    throw new SvgParseError(
      `Expected <svg> root, got <${root?.tagName ?? "?"}>.`,
    );
  }
  return doc;
}

export function serialize(doc: Document): string {
  return new XMLSerializer().serializeToString(doc);
}

export function cloneDoc(doc: Document): Document {
  return parseSvg(serialize(doc));
}

/** Assign an `id` to every drawable element that lacks one.
 *
 * Mutates `doc` in place and returns it for ergonomic chaining. Keeps
 * existing ids untouched so the LLM can refer back to them stably.
 */
export function ensureIds(doc: Document): Document {
  const root = doc.documentElement;
  const used = new Set<string>();
  root.querySelectorAll("[id]").forEach((el) => {
    const id = el.getAttribute("id");
    if (id) used.add(id);
  });

  let counter = 1;
  const nextId = (): string => {
    while (used.has(`el-${counter}`)) counter += 1;
    const id = `el-${counter}`;
    used.add(id);
    counter += 1;
    return id;
  };

  const walk = (node: Element) => {
    const tag = node.tagName.toLowerCase();
    if (DRAWABLE_TAGS.has(tag) && !node.getAttribute("id")) {
      node.setAttribute("id", nextId());
    }
    for (const child of Array.from(node.children)) {
      walk(child as Element);
    }
  };
  walk(root);

  return doc;
}

export function findById(doc: Document, id: string): Element | null {
  return doc.getElementById(id);
}

export function setAttrs(
  doc: Document,
  ids: string[],
  attrs: Record<string, string | null>,
): Document {
  for (const id of ids) {
    const el = doc.getElementById(id);
    if (!el) continue;
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null) {
        el.removeAttribute(key);
      } else {
        el.setAttribute(key, value);
      }
    }
  }
  return doc;
}

export function removeIds(doc: Document, ids: string[]): Document {
  for (const id of ids) {
    const el = doc.getElementById(id);
    if (el && el.parentNode) {
      el.parentNode.removeChild(el);
    }
  }
  return doc;
}

/** Validate that a candidate SVG (e.g. from Grok) is renderable.
 *
 * Throws `SvgParseError` if the document fails to parse, has the wrong
 * root, or cannot be sized. Returns the parsed document on success.
 */
export function replaceFromLlm(svg: string): Document {
  const doc = parseSvg(svg);
  const root = doc.documentElement;
  const hasViewBox = root.hasAttribute("viewBox");
  const hasSize = root.hasAttribute("width") && root.hasAttribute("height");
  if (!hasViewBox && !hasSize) {
    throw new SvgParseError(
      "Returned SVG is missing both viewBox and width/height; cannot render.",
    );
  }
  if (!root.getAttribute("xmlns")) {
    root.setAttribute("xmlns", SVG_NS);
  }
  return doc;
}

export function bboxIntersectsRect(a: SvgRect, b: SvgRect): boolean {
  // Strict overlap: shapes that only touch at an edge are NOT considered
  // selected. This matches user intuition for marquee select.
  return (
    a.x + a.width > b.x &&
    a.x < b.x + b.width &&
    a.y + a.height > b.y &&
    a.y < b.y + b.height
  );
}

export class SvgParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SvgParseError";
  }
}
