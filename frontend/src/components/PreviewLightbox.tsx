import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

type Props = {
  open: boolean;
  onClose: () => void;
  label: string;
  interactive?: boolean;
  children: ReactNode;
};

export default function PreviewLightbox({
  open,
  onClose,
  label,
  interactive = false,
  children,
}: Props) {
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className={`preview-lightbox${interactive ? " preview-lightbox-interactive" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onClick={interactive ? undefined : onClose}
    >
      <button
        type="button"
        className="preview-lightbox-close"
        aria-label="Close preview"
        onClick={(event) => {
          event.stopPropagation();
          onClose();
        }}
      >
        ×
      </button>
      <div
        className={`preview-lightbox-content${interactive ? " preview-lightbox-content-interactive" : ""}`}
        onClick={interactive ? (event) => event.stopPropagation() : undefined}
      >
        {children}
      </div>
    </div>,
    document.body
  );
}
