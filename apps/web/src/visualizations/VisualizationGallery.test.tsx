import { act, create } from "react-test-renderer";
import { describe, expect, it } from "vitest";
import { VisualizationGallery } from "./VisualizationGallery";

describe("VisualizationGallery", () => {
  it("renders all accepted charts and exposes the finite queue", () => {
    let tree: ReturnType<typeof create>;
    act(() => { tree = create(<VisualizationGallery />); });
    expect(tree!.root.findAllByProps({ role: "img" })).toHaveLength(15);
    const queue = tree!.root.findByProps({ children: "Finite queue" });
    const implemented = tree!.root.findByProps({ children: "Implemented" });
    expect(implemented.props["aria-pressed"]).toBe(true);
    expect(queue.props["aria-pressed"]).toBe(false);
    expect(queue.props["aria-controls"]).toBe("gallery-results");
    act(() => queue.props.onClick());
    expect(implemented.props["aria-pressed"]).toBe(false);
    expect(queue.props["aria-pressed"]).toBe(true);
    expect(tree!.root.findAllByType("article")).toHaveLength(61);
    expect(tree!.root.findAllByProps({ role: "img" })).toHaveLength(0);
    expect(tree!.root.findByProps({ className: "sr-only" }).props.children).toEqual([61, " visualization types shown."]);
  });
});
