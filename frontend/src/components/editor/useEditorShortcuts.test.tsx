import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EditorTool } from "./types";
import { useEditorShortcuts } from "./useEditorShortcuts";

function Harness({
  onToolChange,
  enabled = true,
}: {
  onToolChange: (t: EditorTool) => void;
  enabled?: boolean;
}) {
  const { panOverride } = useEditorShortcuts({ onToolChange, enabled });
  return (
    <div>
      <span data-testid="pan">{panOverride ? "on" : "off"}</span>
      <input data-testid="input" placeholder="type here" />
      <textarea data-testid="textarea" />
    </div>
  );
}

describe("useEditorShortcuts", () => {
  it("'s' switches to the select tool", () => {
    const onToolChange = vi.fn<(t: EditorTool) => void>();
    render(<Harness onToolChange={onToolChange} />);

    fireEvent.keyDown(window, { key: "s", code: "KeyS" });
    expect(onToolChange).toHaveBeenCalledWith("select");
  });

  it("'m' switches to the marquee tool", () => {
    const onToolChange = vi.fn<(t: EditorTool) => void>();
    render(<Harness onToolChange={onToolChange} />);

    fireEvent.keyDown(window, { key: "m", code: "KeyM" });
    expect(onToolChange).toHaveBeenCalledWith("marquee");
  });

  it("Space sets panOverride to true on keydown and false on keyup", () => {
    const onToolChange = vi.fn<(t: EditorTool) => void>();
    render(<Harness onToolChange={onToolChange} />);

    expect(screen.getByTestId("pan").textContent).toBe("off");

    fireEvent.keyDown(window, { key: " ", code: "Space" });
    expect(screen.getByTestId("pan").textContent).toBe("on");

    fireEvent.keyUp(window, { key: " ", code: "Space" });
    expect(screen.getByTestId("pan").textContent).toBe("off");
  });

  it("does NOT trigger when typing in an input", () => {
    const onToolChange = vi.fn<(t: EditorTool) => void>();
    render(<Harness onToolChange={onToolChange} />);

    const input = screen.getByTestId("input");
    fireEvent.keyDown(input, { key: "s", code: "KeyS" });
    fireEvent.keyDown(input, { key: "m", code: "KeyM" });
    fireEvent.keyDown(input, { key: " ", code: "Space" });

    expect(onToolChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("pan").textContent).toBe("off");
  });

  it("does NOT trigger when typing in a textarea", () => {
    const onToolChange = vi.fn<(t: EditorTool) => void>();
    render(<Harness onToolChange={onToolChange} />);

    const ta = screen.getByTestId("textarea");
    fireEvent.keyDown(ta, { key: "s", code: "KeyS" });
    expect(onToolChange).not.toHaveBeenCalled();
  });

  it("ignores Cmd+S / Ctrl+S so OS save shortcuts still work", () => {
    const onToolChange = vi.fn<(t: EditorTool) => void>();
    render(<Harness onToolChange={onToolChange} />);

    fireEvent.keyDown(window, { key: "s", code: "KeyS", metaKey: true });
    fireEvent.keyDown(window, { key: "s", code: "KeyS", ctrlKey: true });
    expect(onToolChange).not.toHaveBeenCalled();
  });

  it("does nothing when the hook is disabled", () => {
    const onToolChange = vi.fn<(t: EditorTool) => void>();
    render(<Harness onToolChange={onToolChange} enabled={false} />);

    fireEvent.keyDown(window, { key: "s", code: "KeyS" });
    fireEvent.keyDown(window, { key: " ", code: "Space" });
    expect(onToolChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("pan").textContent).toBe("off");
  });

  it("releases pan on window blur (e.g. user alt-tabs while holding space)", () => {
    const onToolChange = vi.fn<(t: EditorTool) => void>();
    render(<Harness onToolChange={onToolChange} />);

    fireEvent.keyDown(window, { key: " ", code: "Space" });
    expect(screen.getByTestId("pan").textContent).toBe("on");
    fireEvent.blur(window);
    expect(screen.getByTestId("pan").textContent).toBe("off");
  });
});
