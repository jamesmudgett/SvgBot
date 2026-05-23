import { describe, expect, it } from "vitest";

import { EDITOR_ENABLED } from "./config";

describe("EDITOR_ENABLED", () => {
  it("is a boolean (defaults to enabled when env unset in tests)", () => {
    expect(typeof EDITOR_ENABLED).toBe("boolean");
  });
});
