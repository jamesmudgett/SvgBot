import { describe, expect, it } from "vitest";
import {
  bboxIntersectsRect,
  ensureIds,
  parseSvg,
  removeIds,
  replaceFromLlm,
  serialize,
  setAttrs,
} from "./svgDoc";

const FIXTURE = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect id="bg" x="0" y="0" width="100" height="100" fill="#111"/>
  <circle cx="50" cy="50" r="20" fill="#f00"/>
  <path d="M10 10 L90 90"/>
  <g>
    <rect x="5" y="5" width="10" height="10"/>
  </g>
</svg>
`.trim();

describe("parseSvg / serialize", () => {
  it("round-trips a valid SVG", () => {
    const doc = parseSvg(FIXTURE);
    const out = serialize(doc);
    expect(out).toContain('viewBox="0 0 100 100"');
    expect(out).toContain('<svg');
    expect(out).toContain("</svg>");
  });

  it("rejects non-SVG roots", () => {
    expect(() => parseSvg("<html><body/></html>")).toThrow();
    expect(() => parseSvg("not even xml")).toThrow();
  });
});

describe("ensureIds", () => {
  it("adds ids only to drawable elements that lack them", () => {
    const doc = parseSvg(FIXTURE);
    const before = doc.documentElement.querySelectorAll("[id]").length;
    expect(before).toBe(1);

    ensureIds(doc);

    const ids = Array.from(doc.documentElement.querySelectorAll("[id]"))
      .map((el) => el.getAttribute("id"))
      .filter(Boolean) as string[];
    expect(ids).toContain("bg");
    expect(ids.length).toBeGreaterThan(before);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("never overwrites an existing id", () => {
    const doc = parseSvg(FIXTURE);
    ensureIds(doc);
    expect(doc.getElementById("bg")?.getAttribute("fill")).toBe("#111");
  });
});

describe("setAttrs / removeIds", () => {
  it("setAttrs writes attributes to elements by id", () => {
    const doc = parseSvg(FIXTURE);
    setAttrs(doc, ["bg"], { fill: "#abcdef" });
    expect(doc.getElementById("bg")?.getAttribute("fill")).toBe("#abcdef");
  });

  it("removeIds deletes elements by id", () => {
    const doc = parseSvg(FIXTURE);
    removeIds(doc, ["bg"]);
    expect(doc.getElementById("bg")).toBeNull();
  });
});

describe("replaceFromLlm", () => {
  it("accepts a valid SVG document", () => {
    const next = replaceFromLlm(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect/></svg>`,
    );
    expect(serialize(next)).toContain("viewBox=");
  });

  it("rejects garbage", () => {
    expect(() => replaceFromLlm("not svg at all")).toThrow();
  });

  it("rejects an HTML root", () => {
    expect(() => replaceFromLlm("<html><body/></html>")).toThrow();
  });

  it("rejects an SVG missing a viewBox or width/height (cannot render)", () => {
    expect(() =>
      replaceFromLlm('<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'),
    ).toThrow();
  });
});

describe("bboxIntersectsRect", () => {
  it("detects fully-overlapping rectangles", () => {
    expect(
      bboxIntersectsRect(
        { x: 0, y: 0, width: 10, height: 10 },
        { x: 2, y: 2, width: 4, height: 4 },
      ),
    ).toBe(true);
  });

  it("detects partial overlap", () => {
    expect(
      bboxIntersectsRect(
        { x: 0, y: 0, width: 10, height: 10 },
        { x: 8, y: 8, width: 5, height: 5 },
      ),
    ).toBe(true);
  });

  it("disjoint rectangles do not intersect", () => {
    expect(
      bboxIntersectsRect(
        { x: 0, y: 0, width: 10, height: 10 },
        { x: 20, y: 20, width: 4, height: 4 },
      ),
    ).toBe(false);
  });

  it("rectangles that only touch at the edge do not count as intersecting", () => {
    expect(
      bboxIntersectsRect(
        { x: 0, y: 0, width: 10, height: 10 },
        { x: 10, y: 0, width: 4, height: 4 },
      ),
    ).toBe(false);
  });
});
