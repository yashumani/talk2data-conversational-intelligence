import { afterEach, expect, it, vi } from "vitest";
const { render, createRoot } = vi.hoisted(() => { const render = vi.fn(); return { render, createRoot: vi.fn(() => ({ render })) }; });
vi.mock("react-dom/client", () => ({ createRoot }));
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); vi.resetModules(); });
it("mounts the isolated internal workspace", async () => { vi.stubGlobal("document", { getElementById: () => ({}) }); await import("./main"); expect(render).toHaveBeenCalledOnce(); });
it("requires an internal workspace mount", async () => { vi.stubGlobal("document", { getElementById: () => null }); await expect(import("./main")).rejects.toThrow("Workspace root is missing"); });
