import { act, create } from "react-test-renderer";
import { describe, expect, it } from "vitest";
import { VisualizationGallery } from "./VisualizationGallery";

describe("VisualizationGallery", () => {
  it("renders available charts without exposing delivery tracking", () => {
    let tree: ReturnType<typeof create>;
    act(() => { tree = create(<VisualizationGallery />); });
    expect(tree!.root.findAllByProps({ role: "img" })).toHaveLength(25);
    expect(tree!.root.findAll((node) => typeof node.children[0] === "string" && /Batch|accepted|queued|Implemented|Finite queue/.test(String(node.children[0])))).toHaveLength(0);

    const buttons = tree!.root.findAllByType("button");
    const all = buttons.find((button) => button.children[0] === "All")!;
    const distribution = buttons.find((button) => button.children[0] === "Distribution")!;
    expect(all.props["aria-pressed"]).toBe(true);
    expect(distribution.props["aria-pressed"]).toBe(false);
    expect(distribution.props["aria-controls"]).toBe("visualization-results");
    act(() => distribution.props.onClick());
    expect(all.props["aria-pressed"]).toBe(false);
    expect(distribution.props["aria-pressed"]).toBe(true);
    expect(tree!.root.findAllByType("article")).toHaveLength(6);
    expect(tree!.root.findByProps({ className: "sr-only" }).props.children).toEqual([6, " visualization examples shown."]);
  });

  it("searches by label, purpose, and guidance", () => {
    let tree: ReturnType<typeof create>;
    act(() => { tree = create(<VisualizationGallery />); });
    const search = tree!.root.findByProps({ type: "search" });
    act(() => search.props.onChange({ target: { value: "correlation" } }));
    expect(tree!.root.findAllByType("article")).toHaveLength(1);
    expect(tree!.root.findByType("h3").children).toEqual(["Correlogram"]);
  });
});
