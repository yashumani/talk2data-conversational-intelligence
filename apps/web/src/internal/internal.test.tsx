import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { InternalApp } from "./InternalApp";
import { useInternalWorkspace } from "./useInternalWorkspace";
import { internalApi, internalRequest, type InternalRun } from "./api";
import { ApiError } from "../lib/api";

const definition = { id: "MOBILE_ACTIVATIONS", name: "Activations", definition: "Successful connections", owner: "Owner", definition_version: 1, aliases: [] };
const identity = { user_id: "analyst", tenant_id: "tenant", scope_id: "scope", source_binding: "binding" };
const conversation = { conversation_id: "conversation", revision: 0, title: "New conversation", latest_run_id: null };
const workspace = { identity, definitions: { revision: 0, mode: "SEPARATE_REVIEWER" as const, snapshot_id: "snapshot", version: "1", effective_from: "2026-01-01", status: "PUBLISHED" as const, metrics: [definition], dimensions: [], drafts: [], events: [] }, conversations: [], language: { provider: "rules" } };
const request = { client_request_id: "request", conversation_id: "conversation", expected_revision: 0, question: "mobile activations", as_of: "2026-08-01T12:00:00Z", definition_snapshot_id: "snapshot" };
const initial: InternalRun = { run_id: "run", request, source_binding: "binding", status: "RUNNING", sequence: 1, progress: null, result: null, error_code: null, message: "Processing" };
const final: InternalRun = { ...initial, status: "COMPLETED", sequence: 3, result: { status: "ANSWERED", message: "3100", session_id: "session", answer: { headline: "Activations", text: "3100 successful activations", caveats: ["Approved scope"] }, receipt: { receipt_id: "receipt", source_kind: "bigquery", source_fingerprint: null, result_hash: "hash", result_rows: [], row_count: 1, resolved_start: "2026-07-01", resolved_end: "2026-07-31", warnings: [] }, verification: { status: "VERIFIED", checks: [], failures: [] }, query_ir: null, warnings: [], semantic_context: { snapshot_id: "snapshot", metric: definition, dimensions: [], publication_sequence: 1, effective_from: "2026-01-01" } } };
const history = { conversation: { ...conversation, revision: 1, latest_run_id: "run" }, runs: [{ run_id: "run", question: "mobile activations", status: "COMPLETED" }] };
const stored = new Map<string, string>();
const pendingKey = "talk2data.internal.pending.v1";
let renderer: ReactTestRenderer | undefined;
let hook: ReturnType<typeof useInternalWorkspace>;
function Probe() { hook = useInternalWorkspace(); return null; }
async function action(f: () => unknown) { await act(async () => { await f(); }); }
async function mount(element = <Probe />) { await action(() => { renderer = create(element); }); }
function text() { return JSON.stringify(renderer?.toJSON()); }
function button(name: string) { return renderer!.root.findAllByType("button").find(n => n.children.join("") === name)!; }

beforeEach(() => {
  stored.clear(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("sessionStorage", { getItem: (k: string) => stored.get(k) ?? null, setItem: (k: string, v: string) => stored.set(k, v), removeItem: (k: string) => stored.delete(k) });
  vi.spyOn(internalApi, "load").mockResolvedValue(workspace);
  vi.spyOn(internalApi, "create").mockResolvedValue(conversation);
  vi.spyOn(internalApi, "history").mockResolvedValue(history);
  vi.spyOn(internalApi, "submit").mockImplementation(async payload => ({ ...initial, request: payload }));
  vi.spyOn(internalApi, "get").mockResolvedValue(final);
  vi.spyOn(internalApi, "cancel").mockResolvedValue({ ...initial, status: "CANCELLATION_REQUESTED" });
  vi.spyOn(internalApi, "watch").mockImplementation(async (run, _, receive) => { const done = { ...final, request: run.request }; receive(done); return done; });
});
afterEach(async () => { if (renderer) await action(() => renderer!.unmount()); renderer = undefined; vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("keeps the internal workspace separate and persists before submission", async () => {
  await mount(); await action(() => hook.ask("ignored", "2026-08-01"));
  expect(internalApi.submit).not.toHaveBeenCalled();
  await action(() => hook.create());
  vi.mocked(internalApi.submit).mockImplementation(async payload => {
    expect(JSON.parse(stored.get(pendingKey)!).request).toEqual(payload);
    expect(payload).not.toHaveProperty("source_fingerprint");
    return { ...initial, request: payload };
  });
  await action(() => hook.ask(" mobile activations ", "2026-08-01"));
  expect(hook.run?.result?.message).toBe("3100"); expect(hook.pending).toBe(false);
  expect(stored.has(pendingKey)).toBe(false);
  await action(() => hook.cancel()); expect(internalApi.cancel).not.toHaveBeenCalled();
  await action(() => hook.select("conversation")); await action(() => hook.view("run"));
  expect(hook.history).toEqual(history);
});

it("recovers the exact request after a lost acknowledgement", async () => {
  await mount(); await action(() => hook.create());
  vi.mocked(internalApi.submit).mockRejectedValueOnce(new TypeError("Disconnected"));
  await action(() => hook.ask("mobile activations", "2026-08-01"));
  expect(hook.pending).toBe(true); const sent = vi.mocked(internalApi.submit).mock.calls[0][0];
  await action(() => hook.ask("duplicate", "2026-08-01"));
  await action(() => hook.refresh());
  expect(vi.mocked(internalApi.submit).mock.calls[1][0]).toEqual(sent);
  expect(hook.pending).toBe(false);
});

it("restores a pending request after reload and rejects changed authority", async () => {
  stored.set(pendingKey, JSON.stringify({ scope: "scope", binding: "binding", request }));
  await mount(); expect(internalApi.submit).toHaveBeenCalledWith(request);
  stored.set(pendingKey, JSON.stringify({ scope: "other", binding: "binding", request }));
  await action(() => hook.refresh()); expect(hook.error).toContain("was not resent");
  expect(stored.has(pendingKey)).toBe(false);
  stored.set(pendingKey, "broken"); await action(() => hook.refresh()); expect(hook.error).toBeTruthy();
});

it("restores server history across devices and rejects a changed source", async () => {
  vi.mocked(internalApi.load).mockResolvedValue({ ...workspace, conversations: [conversation] });
  await mount(); expect(hook.run).toEqual(final);
  vi.mocked(internalApi.get).mockResolvedValue({ ...final, source_binding: "other" });
  await action(() => hook.refresh()); expect(hook.error).toContain("data connection changed");
  vi.mocked(internalApi.history).mockResolvedValue({ conversation, runs: [] });
  await action(() => hook.refresh()); await action(() => hook.select("conversation"));
  expect(hook.run).toBeNull();
});

it("clears sensitive views on access loss and handles non-error failures", async () => {
  await mount(); await action(() => hook.cancel());
  vi.mocked(internalApi.load).mockRejectedValueOnce(new ApiError(401, "Access expired"));
  await action(() => hook.refresh()); expect(hook.state).toBeNull(); expect(hook.run).toBeNull();
  await action(() => hook.view("unused"));
  vi.mocked(internalApi.load).mockRejectedValueOnce("offline");
  await action(() => hook.refresh()); expect(hook.error).toContain("could not complete");
});

it("allows cancellation while the stream is active and blocks another submission", async () => {
  await mount(); await action(() => hook.create());
  let finish!: (value: InternalRun) => void;
  vi.mocked(internalApi.watch).mockImplementation((run, _, receive) => { receive(run); return new Promise(resolve => { finish = resolve; }); });
  let asking!: Promise<void>;
  await action(() => { asking = hook.ask("mobile activations", "2026-08-01"); });
  expect(hook.busy).toBe(true);
  await action(() => hook.create()); await action(() => hook.ask("other", "2026-08-01"));
  expect(internalApi.create).toHaveBeenCalledOnce();
  await action(() => hook.cancel()); expect(hook.run?.status).toBe("CANCELLATION_REQUESTED");
  vi.mocked(internalApi.cancel).mockRejectedValueOnce(new Error("Access lost"));
  await action(() => hook.cancel()); expect(hook.state).toBeNull();
  await action(async () => { finish(final); await asking; });
});

it("aborts active streams and ignores completion after unmount", async () => {
  vi.mocked(internalApi.load).mockResolvedValue({ ...workspace, conversations: [conversation] });
  let done!: (value: InternalRun) => void; let signal!: AbortSignal;
  vi.mocked(internalApi.watch).mockImplementation((_, incoming, receive) => { signal = incoming; receive(initial); return new Promise(resolve => { done = resolve; }); });
  await mount(); await action(() => renderer!.unmount()); expect(signal.aborted).toBe(true);
  await action(() => done(final));
});

it("ignores failed or late initial loads after unmount", async () => {
  let resolve!: (value: typeof workspace) => void;
  vi.mocked(internalApi.load).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  await mount(); await action(() => renderer!.unmount()); await action(() => resolve(workspace));
  let reject!: (error: Error) => void;
  vi.mocked(internalApi.load).mockImplementationOnce(() => new Promise((_, r) => { reject = r; }));
  await mount(); await action(() => renderer!.unmount()); await action(() => reject(new Error("offline")));
});

it("renders signed workspace, saved evidence and question controls", async () => {
  vi.mocked(internalApi.load).mockResolvedValue({ ...workspace, conversations: [conversation], language: { provider: "claude" } });
  await mount(<InternalApp />);
  expect(text()).toContain("Live business definitions"); expect(text()).toContain("3100 successful activations");
  expect(text()).not.toContain("Upload CSV"); expect(text()).toContain("Signed in as analyst");
  await action(() => button("New conversation").props.onClick());
  await action(() => renderer!.root.findByType("textarea").props.onChange({ target: { value: "Mobile activations" } }));
  await action(() => renderer!.root.findByType("input").props.onChange({ target: { value: "2026-08-01" } }));
  await action(() => renderer!.root.findByType("form").props.onSubmit({ preventDefault() {} }));
  await action(() => button("mobile activations · COMPLETED").props.onClick());
  await action(() => button("Refresh and resume").props.onClick());
  const choices = renderer!.root.findAllByType("button").filter(node => node.children.join("") === "New conversation");
  await action(() => choices[1].props.onClick());
});

it("renders pending and unauthenticated states without data or credentials", async () => {
  await mount(<InternalApp />); expect(text()).toContain("Create a conversation");
  await action(() => button("New conversation").props.onClick());
  vi.mocked(internalApi.submit).mockRejectedValueOnce(new Error("offline"));
  await action(() => renderer!.root.findByType("form").props.onSubmit({ preventDefault() {} }));
  expect(text()).toContain("awaiting confirmation");
  vi.mocked(internalApi.load).mockRejectedValueOnce(new ApiError(403, "Access changed"));
  await action(() => button("Refresh and resume").props.onClick()); expect(text()).toContain("sign-in gateway");
});

it("renders cancel while work runs", async () => {
  vi.mocked(internalApi.load).mockResolvedValue({ ...workspace, conversations: [conversation] });
  let resolve!: (value: InternalRun) => void;
  vi.mocked(internalApi.watch).mockImplementation((_, __, receive) => { receive(initial); return new Promise(r => { resolve = r; }); });
  await mount(<InternalApp />);
  await action(() => button("Cancel question").props.onClick());
  expect(internalApi.cancel).toHaveBeenCalledWith("run");
  await action(() => resolve(final));
});

it("uses same-origin signed gateway requests with no browser bearer tokens", async () => {
  vi.restoreAllMocks(); const fetch = vi.fn().mockImplementation(async () => new Response("{}", { status: 200 })); vi.stubGlobal("fetch", fetch);
  await internalApi.load(); await internalApi.create(); await internalApi.history("a/b"); await internalApi.get("a/b");
  await internalApi.submit(request); await internalApi.cancel("a/b");
  fetch.mockResolvedValueOnce(new Response(null, { status: 204 })); await internalApi.remove("a/b");
  for (const [url, options] of fetch.mock.calls) {
    expect(url).toMatch(/^\/v1\/internal\//); expect(options.credentials).toBe("same-origin");
    expect(options.redirect).toBe("error"); expect(options.headers).not.toHaveProperty("Authorization");
    expect(options.headers).not.toHaveProperty("X-Demo-Session");
  }
  for (const status of [401, 403, 409, 500]) {
    fetch.mockResolvedValueOnce(new Response(null, { status }));
    await expect(internalRequest("/me")).rejects.toMatchObject({ status });
  }
});

it("replays internal SSE and validates snapshots without resubmission", async () => {
  vi.mocked(internalApi.watch).mockRestore();
  const receive = vi.fn(); const controller = new AbortController();
  const frame = `event: progress\ndata: ${JSON.stringify({ run_id: "run", sequence: 2, status: "COMPLETED", progress: null })}\n\n`;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(frame, { headers: { "Content-Type": "text/event-stream" } })));
  expect(await internalApi.watch(initial, controller.signal, receive)).toEqual(final);
  expect(receive).toHaveBeenCalled(); expect(internalApi.submit).not.toHaveBeenCalled();
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("disconnect")));
  expect(await internalApi.watch(initial, controller.signal, receive)).toEqual(final);
  for (const change of [{ run_id: "other" }, { sequence: 0 }, { source_binding: "other" }, { request: { ...request, conversation_id: "other" } }, { request: { ...request, definition_snapshot_id: "other" } }]) {
    vi.mocked(internalApi.get).mockResolvedValueOnce({ ...final, ...change });
    await expect(internalApi.watch(initial, controller.signal, receive)).rejects.toMatchObject({ status: 409 });
  }
  vi.mocked(internalApi.get).mockResolvedValue(initial);
  await expect(internalApi.watch(initial, controller.signal, receive)).rejects.toMatchObject({ status: 503 });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
  await expect(internalApi.watch(initial, controller.signal, receive)).rejects.toMatchObject({ status: 401 });
  controller.abort(); await expect(internalApi.watch(initial, controller.signal, receive)).rejects.toThrow();
  expect(await internalApi.watch(final, new AbortController().signal, receive)).toEqual(final);
});
