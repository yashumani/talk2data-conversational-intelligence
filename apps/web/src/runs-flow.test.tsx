import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { App } from "./App";
import { ConversationPanel } from "./components/ConversationPanel";
import { useWorkspace } from "./hooks/useWorkspace";
import { api, ApiError } from "./lib/api";
import type { ChatResult, DemoSession, WorkspaceState } from "./lib/contracts";
import { runApi, type RunRequest, type RunSnapshot } from "./lib/runs";

const metric = { id: "MOBILE_ACTIVATIONS", name: "Mobile Activations", definition: "Completed starts",
  owner: "Demo", definition_version: 1, aliases: [] };
const session: DemoSession = { session_token: "session", maximum_bytes: 2000000, maximum_rows: 20000, expires_in_seconds: 1800 };
const loaded: WorkspaceState = {
  source: { source_kind: "csv_demo", metric_ids: [metric.id], dimensions: ["REGION"], row_count: 31,
    coverage_start: "2026-07-01", coverage_end: "2026-07-31", source_fingerprint: "a".repeat(64), uploaded_at: "2026-08-01T00:00:00Z" },
  last_response: null, interpreter: "rules", internal_connections_available: false,
  definition: { domain_pack_version: "1", semantic_snapshot_hash: "b".repeat(64),
    metric: { ...metric, semantic_version: "2", aggregation: "SUM", allowed_dimensions: ["REGION"] } },
  definitions: { revision: 0, mode: "DEMO_SINGLE_USER", snapshot_id: "b".repeat(64), version: "1",
    effective_from: "2026-01-01T00:00:00Z", status: "PUBLISHED", metrics: [metric], dimensions: [], drafts: [], events: [] },
  sync: { enabled: true, durable: true, conversation: { conversation_id: "conversation", revision: 0, latest_run_id: null, title: "New" }, runs: [] },
};
const request: RunRequest = { client_request_id: "request", conversation_id: "conversation", expected_revision: 0,
  question: "Mobile activations last month?", as_of: "2026-08-01T12:00:00Z",
  source_fingerprint: "a".repeat(64), definition_snapshot_id: "b".repeat(64) };
const result: ChatResult = { status: "ANSWERED", message: "3100 activations", session_id: "s", answer: null,
  receipt: null, verification: null, query_ir: null, warnings: [] };
const initial: RunSnapshot = { run_id: "run", request, status: "RUNNING", source_binding: request.source_fingerprint,
  sequence: 1, progress: null, result: null, error_code: null, message: "Working" };
const final: RunSnapshot = { ...initial, status: "COMPLETED", sequence: 12, result, message: "Complete" };
const latest = { ...loaded, last_response: result, sync: { ...loaded.sync!,
  conversation: { ...loaded.sync!.conversation, revision: 1, latest_run_id: "run" },
  runs: [{ run_id: "run", status: "COMPLETED", question: request.question }] } };
const stored = new Map<string, string>();
const sessionKey = "talk2data.csv-demo-session.v1";
const pendingKey = "talk2data.csv-pending-run.v1";
let renderer: ReactTestRenderer;
let hook: ReturnType<typeof useWorkspace>;
function Probe() { hook = useWorkspace(); return null; }
async function action(operation: () => unknown) { await act(async () => { await operation(); }); }
async function mount(element = <Probe />) { await action(() => { renderer = create(element); }); }
async function start() { await mount(); await action(() => hook.start()); await action(() => hook.setAsOf("2026-08-01")); }
function button(label: string) { return renderer.root.findAllByType("button").find(n => n.children.join("") === label)!; }
function rendered() { return JSON.stringify(renderer.toJSON()); }

beforeEach(() => {
  stored.clear();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("sessionStorage", { getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => stored.set(key, value), removeItem: (key: string) => stored.delete(key) });
  vi.spyOn(api, "createSession").mockResolvedValue(session);
  vi.spyOn(api, "state").mockResolvedValue(loaded);
  vi.spyOn(api, "ask").mockResolvedValue(result);
  vi.spyOn(api, "clear").mockResolvedValue(undefined);
  vi.spyOn(runApi, "submit").mockImplementation(async (_, payload) => ({ ...initial, request: payload }));
  vi.spyOn(runApi, "get").mockResolvedValue(final);
  vi.spyOn(runApi, "cancel").mockResolvedValue({ ...initial, status: "CANCELLATION_REQUESTED" });
  vi.spyOn(runApi, "watch").mockImplementation(async (_, run, __, receive) => {
    const completed = { ...final, request: run.request };
    receive(completed);
    return completed;
  });
});
afterEach(async () => { if (renderer) await action(() => renderer.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("submits source and definition pins with a unique request ID and restores the saved answer", async () => {
  await start();
  vi.mocked(api.state).mockResolvedValue(latest);
  await action(() => hook.ask("  Mobile activations last month?  "));
  const submitted = vi.mocked(runApi.submit).mock.calls[0][1];
  expect(submitted).toMatchObject({ ...request, client_request_id: expect.any(String) });
  expect(submitted.client_request_id).toMatch(/^[a-f0-9-]{36}$/);
  expect(hook.currentRun?.status).toBe("COMPLETED");
  expect(hook.state?.last_response).toEqual(result);
  expect(hook.pending).toBe(false);
  expect(stored.has(pendingKey)).toBe(false);
  expect(api.ask).not.toHaveBeenCalled();
  await action(() => hook.cancelRun());
  expect(runApi.cancel).not.toHaveBeenCalled();
  await action(() => hook.viewRun("run"));
  expect(hook.savedRun).toEqual(final);
  await action(() => hook.clear());
  expect(hook.currentRun).toBeNull(); expect(hook.savedRun).toBeNull();
  await action(() => hook.viewRun("ignored")); await action(() => hook.cancelRun());
  expect(runApi.get).toHaveBeenCalledTimes(1);
});

it("keeps the same request ID when submission acknowledgement is lost", async () => {
  await start();
  vi.mocked(runApi.submit).mockRejectedValueOnce(new TypeError("Connection lost"));
  await action(() => hook.ask(request.question));
  expect(hook.pending).toBe(true);
  const saved = JSON.parse(stored.get(pendingKey)!);
  vi.mocked(api.state).mockResolvedValue(latest);
  await action(() => hook.refresh());
  expect(runApi.submit).toHaveBeenLastCalledWith("session", saved.request);
  expect(hook.pending).toBe(false);
  expect(hook.state?.last_response).toEqual(result);
});

it.each([400, 409, 422, 429, 503])("handles preflight rejection or recoverable submission failure %s", async status => {
  await start();
  vi.mocked(runApi.submit).mockRejectedValue(new ApiError(status, "Submission unavailable"));
  await action(() => hook.ask(request.question));
  expect(hook.pending).toBe(status === 429 || status === 503);
  expect(hook.error).toBe("Submission unavailable");
});

it.each([400, 429, 503])("handles pending submission recovery status %s", async status => {
  stored.set(sessionKey, JSON.stringify(session));
  stored.set(pendingKey, JSON.stringify({ token: session.session_token, request }));
  vi.mocked(runApi.submit).mockRejectedValue(new ApiError(status, "Recovery unavailable"));
  await mount();
  expect(hook.pending).toBe(status !== 400);
  expect(hook.error).toBe("Recovery unavailable");
});

it.each(["invalid JSON", JSON.stringify({ token: "foreign", request }), JSON.stringify({ token: "session" })])
("discards malformed or foreign pending state and restores canonical history %#", async saved => {
  stored.set(sessionKey, JSON.stringify(session)); stored.set(pendingKey, saved);
  vi.mocked(api.state).mockResolvedValue(latest);
  await mount();
  expect(runApi.submit).not.toHaveBeenCalled();
  expect(runApi.get).toHaveBeenCalledWith("session", "run");
  expect(hook.currentRun?.status).toBe("COMPLETED");
  expect(stored.has(pendingKey)).toBe(false);
});

it("restores a pending request after page refresh using its original ID", async () => {
  stored.set(sessionKey, JSON.stringify(session));
  stored.set(pendingKey, JSON.stringify({ token: "session", request }));
  await mount();
  expect(runApi.submit).toHaveBeenCalledWith("session", request);
  expect(hook.pending).toBe(false);
});

it("shows an interrupted terminal run without resubmitting it", async () => {
  stored.set(sessionKey, JSON.stringify(session));
  vi.mocked(api.state).mockResolvedValue(latest);
  const interrupted = { ...initial, status: "INTERRUPTED", message: "Worker restarted; review before retrying." };
  vi.mocked(runApi.get).mockResolvedValue(interrupted);
  vi.mocked(runApi.watch).mockImplementation(async (_, run, __, receive) => { receive(run); return run; });
  await mount();
  expect(hook.error).toContain("Worker restarted");
  expect(runApi.submit).not.toHaveBeenCalled();
});

it("allows cancellation during progress and confirms completion after reconnecting", async () => {
  await start();
  let finish!: (run: RunSnapshot) => void;
  vi.mocked(runApi.watch).mockImplementation((_, run, __, receive) => {
    receive(run); return new Promise(resolve => { finish = resolve; });
  });
  let asking!: Promise<void>;
  await act(async () => { asking = hook.ask(request.question); });
  expect(hook.busy).not.toBe("");
  await action(() => hook.cancelRun());
  expect(hook.currentRun?.status).toBe("CANCELLATION_REQUESTED");
  await act(async () => { finish({ ...initial, status: "CANCELLED", message: "Cancelled." }); await asking; });
  expect(hook.pending).toBe(false); expect(hook.error).toBe("Cancelled.");
});

it("recovers a confirmed cancellation after the progress connection failed", async () => {
  await start();
  vi.mocked(runApi.watch).mockImplementation(async (_, run, __, receive) => {
    receive(run); throw new ApiError(503, "Resume progress");
  });
  await action(() => hook.ask(request.question));
  expect(hook.pending).toBe(true);
  vi.mocked(runApi.cancel).mockResolvedValue({ ...initial, status: "CANCELLED" });
  await action(() => hook.cancelRun());
  expect(hook.pending).toBe(false);
  expect(hook.currentRun?.status).toBe("CANCELLED");
});

it.each([new Error("Cancel failed"), "unknown failure"])("shows cancellation errors without claiming cancellation %#", async failure => {
  await start();
  vi.mocked(runApi.watch).mockImplementation(async (_, run, __, receive) => { receive(run); throw new ApiError(503, "Disconnected"); });
  await action(() => hook.ask(request.question));
  vi.mocked(runApi.cancel).mockRejectedValue(failure);
  await action(() => hook.cancelRun());
  expect(hook.currentRun?.status).toBe("RUNNING");
  expect(hook.error).toContain(failure instanceof Error ? "Cancel failed" : "could not be confirmed");
});

it("clears all saved UI state on expired access and ignores component aborts", async () => {
  await start();
  vi.mocked(runApi.submit).mockRejectedValue(new ApiError(401, "Session expired"));
  await action(() => hook.ask(request.question));
  expect(hook.session).toBeNull(); expect(stored.has(pendingKey)).toBe(false);
  await action(() => hook.start()); await action(() => hook.setAsOf("2026-08-01"));
  vi.mocked(runApi.submit).mockRejectedValue(new DOMException("Aborted", "AbortError"));
  await action(() => hook.ask(request.question));
  expect(hook.error).toBe("");
});

it("renders durable and temporary history, resume and cancellation with clear source labels", async () => {
  const onResume = vi.fn(async () => {}), onCancel = vi.fn(async () => {}), onView = vi.fn(async () => {});
  const props = { sync: latest.sync!, run: initial, saved: final, pending: true, busy: false, onResume, onCancel, onView };
  await mount(<ConversationPanel {...props} />);
  expect(rendered()).toContain("restored after a service restart");
  expect(rendered()).toContain("Original source");
  await action(() => button("Cancel question").props.onClick());
  await action(() => button("Resume progress").props.onClick());
  await action(() => button(request.question).props.onClick());
  expect(onCancel).toHaveBeenCalledOnce(); expect(onResume).toHaveBeenCalledOnce(); expect(onView).toHaveBeenCalledWith("run");
  await action(() => renderer.update(<ConversationPanel {...props} sync={{ ...latest.sync!, durable: false }}
    run={{ ...initial, status: "CANCELLATION_REQUESTED" }} saved={{ ...initial, message: "Interrupted" }} busy />));
  expect(rendered()).toContain("temporary"); expect(rendered()).toContain("Interrupted");
  expect(button("Cancel question").props.disabled).toBe(true);
  expect(button(request.question).props.disabled).toBe(true);
  await action(() => renderer.update(<ConversationPanel {...props} run={final} pending={false} />));
  expect(renderer.root.findAllByType("button")).toHaveLength(1);
});

it("keeps source operations disabled while a submitted question is unresolved", async () => {
  vi.mocked(runApi.submit).mockRejectedValue(new ApiError(503, "Connection lost"));
  await mount(<App />);
  await action(() => button("Start CSV demo").props.onClick());
  await action(() => renderer.root.findByProps({ id: "as-of" }).props.onChange({ target: { value: "2026-08-01" } }));
  await action(() => renderer.root.findByProps({ id: "question" }).props.onChange({ target: { value: request.question } }));
  await action(() => renderer.root.findAllByType("form")[0].props.onSubmit({ preventDefault: vi.fn() }));
  expect(button("Ask question").props.disabled).toBe(true);
  expect(button("Resume progress")).toBeTruthy();
});

