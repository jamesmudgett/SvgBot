import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EditorToolbar from "./EditorToolbar";
import type { EditorPrefs, EditorTool } from "./types";

const defaultPrefs: EditorPrefs = {
  showGrid: true,
  showRulers: true,
  overlayOpacity: 0,
};

function renderToolbar(overrides: Partial<React.ComponentProps<typeof EditorToolbar>> = {}) {
  const onToolChange = vi.fn<(t: EditorTool) => void>();
  const onPrefsChange = vi.fn<(p: Partial<EditorPrefs>) => void>();
  const onUndo = vi.fn();
  const onRedo = vi.fn();
  const onResetView = vi.fn();
  const onDelete = vi.fn();
  const onClearRegion = vi.fn();
  const onPickFill = vi.fn<(color: string) => void>();
  const onPickStroke = vi.fn<(color: string) => void>();
  const onDownload = vi.fn();
  const onBack = vi.fn();

  const utils = render(
    <EditorToolbar
      tool="select"
      prefs={defaultPrefs}
      canUndo
      canRedo
      selectionCount={2}
      hasRegion={false}
      onToolChange={onToolChange}
      onPrefsChange={onPrefsChange}
      onUndo={onUndo}
      onRedo={onRedo}
      onResetView={onResetView}
      onDelete={onDelete}
      onClearRegion={onClearRegion}
      onPickFill={onPickFill}
      onPickStroke={onPickStroke}
      onDownload={onDownload}
      onBack={onBack}
      {...overrides}
    />,
  );

  return {
    ...utils,
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
  };
}

describe("EditorToolbar", () => {
  it("changes the active tool when a tool button is clicked", () => {
    const { onToolChange } = renderToolbar();
    fireEvent.click(screen.getByRole("button", { name: /marquee/i }));
    expect(onToolChange).toHaveBeenCalledWith("marquee");
  });

  it("toggles the dot grid", () => {
    const { onPrefsChange } = renderToolbar();
    fireEvent.click(screen.getByRole("button", { name: /grid/i }));
    expect(onPrefsChange).toHaveBeenCalledWith({ showGrid: false });
  });

  it("dispatches undo / redo", () => {
    const { onUndo, onRedo } = renderToolbar();
    fireEvent.click(screen.getByRole("button", { name: /undo/i }));
    fireEvent.click(screen.getByRole("button", { name: /redo/i }));
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onRedo).toHaveBeenCalledTimes(1);
  });

  it("disables undo/redo according to the props", () => {
    renderToolbar({ canUndo: false, canRedo: false });
    expect(screen.getByRole("button", { name: /undo/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /redo/i })).toBeDisabled();
  });

  it("dispatches Delete (and shows selection count)", () => {
    const { onDelete } = renderToolbar();
    expect(screen.getByText(/2 selected/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^delete/i }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("emits chosen fill / stroke colors", () => {
    const { onPickFill, onPickStroke } = renderToolbar();
    const fill = screen.getByLabelText(/fill color/i) as HTMLInputElement;
    fireEvent.input(fill, { target: { value: "#abcdef" } });
    expect(onPickFill).toHaveBeenCalledWith("#abcdef");

    const stroke = screen.getByLabelText(/stroke color/i) as HTMLInputElement;
    fireEvent.input(stroke, { target: { value: "#123456" } });
    expect(onPickStroke).toHaveBeenCalledWith("#123456");
  });

  it("emits Download", () => {
    const { onDownload } = renderToolbar();
    fireEvent.click(screen.getByRole("button", { name: /download/i }));
    expect(onDownload).toHaveBeenCalledTimes(1);
  });

  it("emits overlay-opacity changes via the 'Overlay original (alpha 0-100%)' slider", () => {
    const { onPrefsChange } = renderToolbar({
      prefs: { ...defaultPrefs, overlayOpacity: 0.4 },
    });
    const slider = screen.getByLabelText(
      /overlay original \(alpha 0-100%\)/i,
    ) as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "0.7" } });
    expect(onPrefsChange).toHaveBeenCalled();
    const args = onPrefsChange.mock.calls[onPrefsChange.mock.calls.length - 1]?.[0];
    expect(args?.overlayOpacity).toBeCloseTo(0.7);
  });

  it("hides the region snapshot chip when there is no region", () => {
    renderToolbar({ hasRegion: false });
    expect(screen.queryByRole("button", { name: /clear region/i })).toBeNull();
  });

  it("shows a Clear region chip and dispatches onClearRegion when present", () => {
    const { onClearRegion } = renderToolbar({ hasRegion: true });
    const chip = screen.getByRole("button", { name: /clear region/i });
    fireEvent.click(chip);
    expect(onClearRegion).toHaveBeenCalledTimes(1);
  });
});
