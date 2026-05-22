import { useEffect, useState } from "react";

/** Prepare SVG for browser preview (fix backend ns0: prefixes, add viewBox). */
export function normalizeSvgForPreview(svg: string): string {
  let s = svg.trim();
  s = s.replace(/<\?xml[\s\S]*?\?>\s*/gi, "");
  s = s.replace(/<!--[\s\S]*?-->\s*/g, "");

  // ElementTree fontless output: <ns0:svg xmlns:ns0="..."> breaks strict XML parsers
  s = s.replace(/<ns\d+:/gi, "<");
  s = s.replace(/<\/ns\d+:/gi, "</");
  s = s.replace(
    /\sxmlns:ns\d+="http:\/\/www\.w3\.org\/2000\/svg"/gi,
    ' xmlns="http://www.w3.org/2000/svg"'
  );

  if (!/\bxmlns=/i.test(s)) {
    s = s.replace(/<svg\b/i, '<svg xmlns="http://www.w3.org/2000/svg"');
  }

  if (!/\bviewBox=/i.test(s)) {
    const wMatch = s.match(/\bwidth=["']([^"']+)["']/i);
    const hMatch = s.match(/\bheight=["']([^"']+)["']/i);
    const parse = (v: string | undefined) => {
      if (!v) return 0;
      const n = parseFloat(v.replace(/px|pt|%$/i, ""));
      return Number.isFinite(n) && n > 0 ? n : 0;
    };
    const w = parse(wMatch?.[1]) || 512;
    const h = parse(hMatch?.[1]) || 512;
    s = s.replace(/<svg\b/i, `<svg viewBox="0 0 ${w} ${h}"`);
  }

  return s;
}

type Props = {
  svg: string;
  className?: string;
};

/** Renders SVG via blob URL; use with `.preview-media` inside a sized frame to match the upload preview. */
export default function SvgPreview({ svg, className = "preview-media" }: Props) {
  const [src, setSrc] = useState<string>("");

  useEffect(() => {
    const normalized = normalizeSvgForPreview(svg);
    const blobUrl = URL.createObjectURL(
      new Blob([normalized], { type: "image/svg+xml;charset=utf-8" })
    );
    setSrc(blobUrl);
    return () => URL.revokeObjectURL(blobUrl);
  }, [svg]);

  if (!src) {
    return null;
  }

  return (
    <img className={className} src={src} alt="Vector preview" />
  );
}
