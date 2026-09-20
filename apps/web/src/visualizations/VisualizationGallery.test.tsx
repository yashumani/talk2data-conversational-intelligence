import { act, create } from "react-test-renderer";
import { describe, expect, it } from "vitest";
import { VisualizationGallery } from "./VisualizationGallery";

describe("VisualizationGallery", () => {
  it("renders all accepted charts and exposes the finite queue", () => {
    let tree: ReturnType<typeof create>;
    act(() => { tree = create(<VisualizationGallery />); });
    expect(tree!.root.findAllByProps({ role: "img" })).toHaveLength(15);
    const queue = tree!.root.findByProps({ children: "Finite queue" });
    act(() => queue.props.onClick());
    expect(tree!.root.findAllByType("article")).toHaveLength(61);
    expect(tree!.root.findAllByProps({ role: "img" })).toHaveLength(0);
  });
});
