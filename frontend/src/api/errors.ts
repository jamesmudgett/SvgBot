/** Empty = Vite dev proxy. Set VITE_API_BASE=http://127.0.0.1:8000 to call API directly. */
export const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const IS_DEV = import.meta.env.DEV;

export function apiUrl(path: string): string {
  const base = API_BASE.replace(/\/$/, "");
  return `${base}${path}`;
}

function userError(message: string): Error {
  return new Error(message);
}

function parseDetail(text: string): string | null {
  try {
    const body = JSON.parse(text) as { detail?: string };
    if (typeof body.detail === "string" && body.detail.trim()) {
      return body.detail.trim();
    }
  } catch {
    /* not JSON */
  }
  return null;
}

function wrapFetchError(err: unknown, context: "upload" | "poll" | "health"): Error {
  const isNetwork =
    err instanceof TypeError &&
    /fetch|network|aborted|failed to fetch/i.test(err.message);

  if (!isNetwork) {
    return err instanceof Error ? err : new Error(String(err));
  }

  if (IS_DEV) {
    const hint = API_BASE
      ? API_BASE
      : "http://127.0.0.1:8000 (via Vite proxy when using npm run dev)";
    return userError(
      `Cannot reach the API (${context}). Is the backend running at ${hint}? ` +
        "Start it with ./run.sh or: cd backend && uvicorn app.main:app --reload --port 8000"
    );
  }

  if (context === "poll") {
    return userError(
      "Something went wrong while processing your image. " +
        "If you uploaded a large photo, try resizing it to under 1536 px on the longest side."
    );
  }

  if (context === "upload") {
    return userError(
      "Could not upload your image. Check your connection and try again. " +
        "Large photos may need to be resized first."
    );
  }

  return userError("Could not reach the server. Please try again in a moment.");
}

function httpError(status: number, text: string, context: "upload" | "poll"): Error {
  const detail = parseDetail(text);
  if (detail) {
    return userError(detail);
  }

  if (status === 413) {
    return userError(
      "This image is too large. Photos must be under 1536 px on the longest side."
    );
  }

  if (context === "poll" && status === 404) {
    return userError(
      "This conversion was interrupted. Please try uploading again."
    );
  }

  if (IS_DEV) {
    return userError(text || `Request failed (${status})`);
  }

  if (context === "poll") {
    return userError(
      "Something went wrong while processing your image. Try a smaller image."
    );
  }

  return userError("Upload failed. Try a smaller image or a different file format.");
}
