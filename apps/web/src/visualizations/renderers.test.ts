import { describe, expect, it } from "vitest";
import { acceptedVisualizations } from "./catalog";
import { optionFor } from "./renderers";

describe("Batch 1 renderers", () => {
  it.each(acceptedVisualizations)("creates a deterministic option for $id", (entry) => {
    const first = optionFor(entry.id);
    expect(first).toEqual(optionFor(entry.id));
    expect(first.animation).toBe(false);
    expect(first.series).toBeTruthy();
  });

  it("fails closed for an unaccepted renderer", () => {
    expect(() => optionFor("sankey")).toThrow("Unsupported accepted renderer");
  });
});
