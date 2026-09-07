import { afterEach, expect, it, vi } from "vitest";

const { render, createRoot } = vi.hoisted(() => {
  const render = vi.fn(); return { render, createRoot: vi.fn(() => ({ render })) };
});
vi.mock("react-dom/client", () => ({ createRoot }));
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); vi.resetModules(); });
it("mounts the application into the configured root", async () => {
  const root = {}; vi.stubGlobal("document", { getElementById: vi.fn(() => root) });
  await import("./main"); expect(createRoot).toHaveBeenCalledWith(root); expect(render).toHaveBeenCalledOnce();
});
it("fails visibly when the HTML entry point has no root", async () => {
  vi.stubGlobal("document", { getElementById: () => null });
  await expect(import("./main")).rejects.toThrow("Workspace root is missing"); expect(createRoot).not.toHaveBeenCalled();
});
