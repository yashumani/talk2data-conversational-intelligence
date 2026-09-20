import { describe, expect, it } from "vitest";
import { acceptedVisualizations } from "./catalog";
import { optionFor } from "./renderers";

describe("accepted visualization renderers", () => {
  it.each(acceptedVisualizations)("creates a deterministic option for $id", (entry) => {
    const first = optionFor(entry.id);
    expect(first).toEqual(optionFor(entry.id));
    expect(first.animation).toBe(false);
    expect(first.series).toBeTruthy();
  });

  it("fails closed for an unaccepted renderer", () => {
    expect(() => optionFor("sankey")).toThrow("Unsupported accepted renderer");
  });

  it("executes custom distribution geometry deterministically", () => {
    const violin = optionFor("violin") as { series: [{ renderItem: (params: unknown, api: unknown) => { type: string } }] };
    const values = [0, 18, 28, 36, 49, 62];
    const shape = violin.series[0].renderItem({}, {
      value: (index: number) => values[index],
      coord: ([category, value]: number[]) => [category * 80 + 40, 180 - value * 2],
      size: () => [80, 0],
    });
    expect(shape.type).toBe("polygon");

    const ridge = optionFor("ridgeline") as { yAxis: { axisLabel: { formatter: (value: number) => string } } };
    expect(ridge.yAxis.axisLabel.formatter(2)).toBe("South");
  });
});
