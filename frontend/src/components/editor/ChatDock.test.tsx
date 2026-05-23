import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type MockInstance,
} from "vitest";

import ChatDock from "./ChatDock";

const SAMPLE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>';
const RESPONSE_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect/></svg>';

let fetchMock: MockInstance;

beforeEach(() => {
  fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    new Response(
      JSON.stringify({
        svg: RESPONSE_SVG,
        summary: "Recolored fill",
        model: "grok-4-stub",
        ms: 12,
        tokens_in: 5,
        tokens_out: 8,
        quota_remaining: 4,
      }),
      {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "X-Editor-Quota-Remaining": "4",
        },
      },
    ),
  );
});

afterEach(() => {
  fetchMock.mockRestore();
});

function renderDock(props: Partial<React.ComponentProps<typeof ChatDock>> = {}) {
  const onApply = vi.fn();
  const utils = render(
    <ChatDock
      jobId="job-1"
      svg={SAMPLE_SVG}
      selectedIds={["el-1"]}
      region={null}
      onApply={onApply}
      {...props}
    />,
  );
  return { ...utils, onApply };
}

describe("ChatDock", () => {
  it("opens by default and renders the chat surface", () => {
    renderDock();
    // No "Open chat" launcher should be visible: the dock starts expanded.
    expect(screen.queryByRole("button", { name: /open chat/i })).toBeNull();
    expect(screen.getByRole("dialog", { name: /llm editor chat/i })).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/describe the change/i),
    ).toBeInTheDocument();
  });

  it("posts to /api/editor/llm-edit (with include_original true by default) and renders Apply/Discard", async () => {
    renderDock();

    const input = screen.getByPlaceholderText(/describe the change/i);
    fireEvent.change(input, { target: { value: "Make it green" } });

    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /apply/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /discard/i })).toBeInTheDocument();
    expect(screen.getByText(/recolored fill/i)).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/editor\/llm-edit$/);
    const body = JSON.parse(String(init.body));
    expect(body.instruction).toBe("Make it green");
    expect(body.svg).toBe(SAMPLE_SVG);
    expect(body.selected_ids).toEqual(["el-1"]);
    // New default: Reference original is checked, so include_original=true.
    expect(body.include_original).toBe(true);
    expect(body.region).toBeUndefined();
    expect(body.job_id).toBe("job-1");
  });

  it("Apply forwards the new SVG to the parent", async () => {
    const { onApply } = renderDock();

    fireEvent.change(screen.getByPlaceholderText(/describe the change/i), {
      target: { value: "Tweak it" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    const apply = await screen.findByRole("button", { name: /apply/i });
    fireEvent.click(apply);

    expect(onApply).toHaveBeenCalledWith(RESPONSE_SVG, "Recolored fill");
  });

  it("omits the original when the user unchecks Reference original", async () => {
    renderDock();

    // Default-checked, so clicking once unchecks.
    fireEvent.click(screen.getByLabelText(/reference original/i));

    fireEvent.change(screen.getByPlaceholderText(/describe the change/i), {
      target: { value: "Just structural" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.include_original).toBe(false);
  });

  it("forwards the marquee region snapshot in the request body", async () => {
    renderDock({
      region: { x: 12, y: 34, width: 56, height: 78 },
    });

    fireEvent.change(screen.getByPlaceholderText(/describe the change/i), {
      target: { value: "Smooth corners in this box" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.region).toEqual({ x: 12, y: 34, width: 56, height: 78 });
  });

  it("renders an error card when the server returns 503 (no API key)", async () => {
    fetchMock.mockImplementationOnce(async () =>
      new Response(
        JSON.stringify({
          detail: "Grok (xAI) is not configured on this server.",
          code: "no_api_key",
        }),
        {
          status: 503,
          headers: {
            "Content-Type": "application/json",
            "X-Editor-Quota-Remaining": "unlimited",
          },
        },
      ),
    );

    renderDock();
    fireEvent.change(screen.getByPlaceholderText(/describe the change/i), {
      target: { value: "Recolor" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() =>
      expect(screen.getByText(/not configured/i)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /apply/i })).toBeNull();
  });
});
