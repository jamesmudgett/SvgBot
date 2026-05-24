import { useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import PreviewLightbox from "./PreviewLightbox";

type Props = {
  label: string;
  frameStyle?: CSSProperties;
  lightbox: ReactNode;
  interactive?: boolean;
  children: ReactNode;
};

export default function ExpandablePreview({
  label,
  frameStyle,
  lightbox,
  interactive = false,
  children,
}: Props) {
  const [open, setOpen] = useState(false);

  const openPreview = () => setOpen(true);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPreview();
    }
  };

  return (
    <>
      <div
        className="preview-frame preview-frame-expandable"
        style={frameStyle}
        role="button"
        tabIndex={0}
        aria-label={`Expand ${label}`}
        onClick={openPreview}
        onKeyDown={onKeyDown}
      >
        {children}
      </div>
      <PreviewLightbox
        open={open}
        onClose={() => setOpen(false)}
        label={label}
        interactive={interactive}
      >
        {lightbox}
      </PreviewLightbox>
    </>
  );
}
