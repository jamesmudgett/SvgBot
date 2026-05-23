import { useCallback, useRef, useState } from "react";

import { llmEditSvg, type LlmEditError } from "../../api/client";
import type { ChatMessage } from "./types";
import type { SvgRect } from "../../utils/svgDoc";

interface Props {
  jobId: string;
  svg: string;
  selectedIds: string[];
  /** Persisted marquee rectangle in user-space, or null. Forwarded to
   * Grok so the LLM knows the user is asking for changes inside a
   * specific bounding box. */
  region: SvgRect | null;
  /** Called when the user accepts a Grok-proposed SVG. The parent is
   * responsible for snapshotting and replacing the editor doc. */
  onApply: (newSvg: string, summary: string) => void;
}

let nextId = 1;
const uid = () => `m-${nextId++}`;

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="14"
      height="14"
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

export default function ChatDock({
  jobId,
  svg,
  selectedIds,
  region,
  onApply,
}: Props) {
  const [open, setOpen] = useState(true);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [includeOriginal, setIncludeOriginal] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const listRef = useRef<HTMLDivElement | null>(null);

  const append = useCallback((m: ChatMessage) => {
    setMessages((prev) => {
      const next = [...prev, m];
      queueMicrotask(() => {
        const list = listRef.current;
        if (list && typeof list.scrollTo === "function") {
          list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
        } else if (list) {
          list.scrollTop = list.scrollHeight;
        }
      });
      return next;
    });
  }, []);

  const send = useCallback(async () => {
    const instruction = text.trim();
    if (!instruction || busy) return;

    append({ id: uid(), role: "user", text: instruction });
    setText("");
    setBusy(true);

    try {
      const res = await llmEditSvg({
        job_id: jobId,
        svg,
        instruction,
        selected_ids: selectedIds,
        include_original: includeOriginal,
        region: region
          ? {
              x: region.x,
              y: region.y,
              width: region.width,
              height: region.height,
            }
          : undefined,
      });
      append({
        id: uid(),
        role: "assistant",
        text: res.summary || "Updated SVG.",
        pendingSvg: res.svg,
        modelMs: res.ms,
      });
    } catch (err) {
      const e = err as LlmEditError;
      const message =
        e?.code === "no_api_key"
          ? "Grok is not configured on this server. Set XAI_API_KEY in backend/.env to enable LLM revisions."
          : e?.message || "LLM edit failed.";
      append({
        id: uid(),
        role: "assistant",
        text: message,
        isError: true,
      });
    } finally {
      setBusy(false);
    }
  }, [
    text,
    busy,
    append,
    includeOriginal,
    jobId,
    svg,
    selectedIds,
    region,
  ]);

  const apply = useCallback(
    (id: string) => {
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== id || !m.pendingSvg) return m;
          onApply(m.pendingSvg, m.text);
          return { ...m, applied: true };
        }),
      );
    },
    [onApply],
  );

  const discard = useCallback((id: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id
          ? {
              ...m,
              pendingSvg: undefined,
              applied: false,
              text: `${m.text} (discarded)`,
            }
          : m,
      ),
    );
  }, []);

  if (!open) {
    return (
      <button
        type="button"
        className="editor-chat-launcher"
        onClick={() => setOpen(true)}
        aria-label="Open chat"
      >
        Ask Grok
      </button>
    );
  }

  const pinSummary: string[] = [];
  if (selectedIds.length > 0) {
    pinSummary.push(`${selectedIds.length} element(s) pinned`);
  }
  if (region) {
    pinSummary.push("region snapshot pinned");
  }

  return (
    <aside className="editor-chat-dock" role="dialog" aria-label="LLM editor chat">
      <header className="editor-chat-header">
        <div>
          <strong>Ask Grok</strong>
          <p className="editor-chat-meta">
            {pinSummary.length > 0
              ? `${pinSummary.join(" + ")} for your next request`
              : "No selection: revisions apply to the whole SVG"}
          </p>
        </div>
        <button
          type="button"
          className="editor-chat-close"
          onClick={() => setOpen(false)}
          aria-label="Close chat"
          title="Close"
        >
          <CloseIcon />
        </button>
      </header>

      <div ref={listRef} className="editor-chat-messages">
        {messages.length === 0 && (
          <p className="editor-chat-hint">
            Describe the change you want. Examples: "make the inner shape pure
            red", "remove the background rectangle", "smooth the corners".
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`editor-chat-message editor-chat-${m.role}${
              m.isError ? " editor-chat-error" : ""
            }`}
          >
            <p>{m.text}</p>
            {m.pendingSvg && !m.applied && (
              <div className="editor-chat-actions">
                <button
                  type="button"
                  className="editor-chat-apply"
                  onClick={() => apply(m.id)}
                  aria-label="Apply"
                >
                  Apply
                </button>
                <button
                  type="button"
                  className="editor-chat-discard"
                  onClick={() => discard(m.id)}
                  aria-label="Discard"
                >
                  Discard
                </button>
              </div>
            )}
            {m.applied && (
              <p className="editor-chat-applied-tag">Applied</p>
            )}
          </div>
        ))}
        {busy && (
          <div className="editor-chat-message editor-chat-assistant editor-chat-busy">
            <span className="editor-chat-typing" aria-label="Grok is typing">
              <span />
              <span />
              <span />
            </span>
          </div>
        )}
      </div>

      <form
        className="editor-chat-input"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <div className="editor-chat-row">
          <input
            type="text"
            placeholder="Describe the change you want"
            value={text}
            onChange={(event) => setText(event.target.value)}
            disabled={busy}
            aria-label="Instruction"
          />
          <button
            type="submit"
            className="editor-chat-send"
            disabled={busy || !text.trim()}
          >
            Send
          </button>
        </div>
        <label className="editor-chat-checkbox">
          <input
            type="checkbox"
            checked={includeOriginal}
            onChange={(event) => setIncludeOriginal(event.target.checked)}
          />
          <span>Reference original</span>
        </label>
      </form>
    </aside>
  );
}
