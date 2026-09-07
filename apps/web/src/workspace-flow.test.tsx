import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { App } from "./App";
import { DataSourcePanel } from "./components/DataSourcePanel";
import { ChatPanel } from "./components/ChatPanel";
import { EvidencePanel } from "./components/EvidencePanel";
import { useWorkspace } from "./hooks/useWorkspace";
import { api, ApiError } from "./lib/api";
import type { ChatResult, DemoSession, Source, WorkspaceState } from "./lib/contracts";

const session: DemoSession = { session_token: "test-token", maximum_bytes: 2_000_000,
  maximum_rows: 20_000, expires_in_seconds: 1800 };
const source: Source = { source_kind: "csv_demo", metric_ids: ["MOBILE_ACTIVATIONS"],
  dimensions: ["REGION"], row_count: 31, coverage_start: "2026-07-01", coverage_end: "2026-07-31",
  source_fingerprint: "a".repeat(64), uploaded_at: "2026-08-01T00:00:00Z" };
const empty: WorkspaceState = { source: null, last_response: null, interpreter: "rules",
  internal_connections_available: false, definition: { domain_pack_version: "1", semantic_snapshot_hash: "b",
    metric: { id: "MOBILE_ACTIVATIONS", name: "Mobile Activations", definition: "Completed new activations",
      semantic_version: "2", aggregation: "SUM", allowed_dimensions: ["REGION"] } } };
const result: ChatResult = { status: "ANSWERED", message: "31 activations", session_id: "session",
  answer: { headline: "Mobile Activations", text: "31 activations", caveats: ["Demonstration data"] },
  verification: { status: "VERIFIED", checks: ["RESULT_HASH_MATCHED"], failures: [] },
  receipt: { receipt_id: "receipt", source_kind: "csv_demo", source_fingerprint: source.source_fingerprint,
    result_hash: "c", result_rows: [{ value: 31 }], row_count: 1, resolved_start: "2026-07-01",
    resolved_end: "2026-07-31", warnings: [] },
  query_ir: { semantic_version: "2", semantic_snapshot_hash: "b", plan_hash: "d" }, warnings: [] };
const loaded = { ...empty, source };
const key = "talk2data.csv-demo-session.v1";
let renderer: ReactTestRenderer;
let hook: ReturnType<typeof useWorkspace>;
const stored = new Map<string, string>();

function Probe() { hook = useWorkspace(); return null; }
async function mount(element = <Probe />) { await act(async () => { renderer = create(element); }); }
async function run(operation: () => unknown) { await act(async () => { await operation(); }); }
function textContent() { return JSON.stringify(renderer.toJSON()); }

beforeEach(() => {
  stored.clear();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("sessionStorage", { getItem: (k: string) => stored.get(k) ?? null,
    setItem: (k: string, v: string) => stored.set(k, v), removeItem: (k: string) => stored.delete(k) });
  vi.spyOn(api, "createSession").mockResolvedValue(session);
  vi.spyOn(api, "state").mockResolvedValue(empty);
  vi.spyOn(api, "upload").mockResolvedValue(source);
  vi.spyOn(api, "ask").mockResolvedValue(result);
  vi.spyOn(api, "clear").mockResolvedValue(undefined);
});
afterEach(async () => { if (renderer) await run(() => renderer.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("workspace state synchronization", () => {
  it("starts, validates, uploads, binds a question to its source, refreshes and clears", async () => {
    await mount();
    await run(() => hook.ask("ignored")); await run(() => hook.refresh());
    await run(() => hook.clear()); await run(() => hook.upload(new File(["x"], "x.csv")));
    expect(api.ask).not.toHaveBeenCalled(); expect(api.upload).not.toHaveBeenCalled();
    await run(() => hook.start());
    expect(JSON.parse(stored.get(key)!)).toEqual(session);
    await run(() => hook.ask("no source"));
    await run(() => hook.upload(new File(["x"], "bad.txt")));
    expect(hook.error).toContain(".csv"); expect(api.upload).not.toHaveBeenCalled();
    vi.mocked(api.state).mockResolvedValue(loaded);
    const file = new File(["date,region,channel,activations"], "sample.csv");
    await run(() => hook.upload(file));
    expect(hook.asOf).toBe("2026-08-01"); expect(hook.state).toEqual(loaded);
    await run(() => hook.setAsOf("")); await run(() => hook.ask("no date"));
    expect(api.ask).not.toHaveBeenCalled();
    await run(() => hook.setAsOf("2026-08-17"));
    vi.mocked(api.state).mockResolvedValue({ ...loaded, last_response: result });
    await run(() => hook.ask("  What were mobile activations last month?  "));
    expect(api.ask).toHaveBeenCalledWith("test-token", "What were mobile activations last month?", "2026-08-17", source.source_fingerprint, undefined);
    expect(hook.state?.last_response).toEqual(result);
    await run(() => hook.refresh()); expect(hook.asOf).toBe("2026-08-17");
    vi.mocked(api.state).mockResolvedValue({ ...loaded, source: { ...source, source_fingerprint: "new", coverage_end: "2026-08-31" } });
    await run(() => hook.refresh()); expect(hook.asOf).toBe("2026-09-01");
    vi.mocked(api.state).mockResolvedValue(empty);
    await run(() => hook.refresh()); expect(hook.state?.source).toBeNull();
    await run(() => hook.clear());
    expect(hook.session).toBeNull(); expect(hook.state).toBeNull(); expect(hook.asOf).toBe(""); expect(stored.has(key)).toBe(false);
  });

  it.each(["{invalid", "null", "{}", '{"session_token":12,"maximum_bytes":100}', '{"session_token":"x"}'])("discards corrupt saved state: %s", async saved => {
    stored.set(key, saved); await mount(); expect(stored.has(key)).toBe(false); expect(api.state).not.toHaveBeenCalled();
  });
  it.each([empty, loaded])("restores server state without trusting a cached answer", async snapshot => {
    stored.set(key, JSON.stringify(session)); vi.mocked(api.state).mockResolvedValue(snapshot);
    await mount(); expect(hook.state).toEqual(snapshot); expect(hook.asOf).toBe(snapshot.source ? "2026-08-01" : "");
  });
  it("expires the session on 401 and never releases the old answer", async () => {
    stored.set(key, JSON.stringify(session)); vi.mocked(api.state).mockResolvedValue({ ...loaded, last_response: result });
    await mount(); vi.mocked(api.ask).mockRejectedValue(new ApiError(401, "Session expired"));
    await run(() => hook.ask("question"));
    expect(hook.session).toBeNull(); expect(hook.state).toBeNull(); expect(stored.has(key)).toBe(false);
    expect(hook.error).toBe("Session expired"); expect(hook.busy).toBe("");
  });
  it.each([new Error("Offline"), "unknown"])("reports failures and allows a retry: %s", async failure => {
    vi.mocked(api.createSession).mockRejectedValueOnce(failure); await mount(); await run(() => hook.start());
    expect(hook.error).toBe(failure instanceof Error ? "Offline" : "Something went wrong. Please retry.");
    await run(() => hook.start()); expect(hook.error).toBe(""); expect(hook.session).toEqual(session);
  });
  it("prevents overlapping operations", async () => {
    let finish!: (value: DemoSession) => void;
    vi.mocked(api.createSession).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    await mount(); let pending!: Promise<void>;
    await run(() => { pending = hook.start(); });
    expect(hook.busy).toBe("Opening demo session"); await run(() => hook.start());
    expect(api.createSession).toHaveBeenCalledTimes(1);
    await run(async () => { finish(session); await pending; }); expect(hook.busy).toBe("");
  });
  it("removes an old answer as soon as a replacement upload succeeds even if refresh fails", async () => {
    stored.set(key, JSON.stringify(session)); vi.mocked(api.state).mockResolvedValue({ ...loaded, last_response: result });
    await mount(); const replacement = { ...source, source_fingerprint: "replacement" };
    vi.mocked(api.upload).mockResolvedValue(replacement); vi.mocked(api.state).mockRejectedValue(new Error("Refresh failed"));
    await run(() => hook.upload(new File(["data"], "new.csv")));
    expect(hook.state?.source).toEqual(replacement); expect(hook.state?.last_response).toBeNull();
    expect(hook.error).toBe("Refresh failed");
  });
});

describe("rendered React interactions", () => {
  it("drives the main UI through upload, answer, refresh, and clear", async () => {
    await mount(<App />); expect(textContent()).toContain("Start CSV demo");
    const button = (label: string) => renderer.root.findAllByType("button").find(node => node.children.join("") === label)!;
    await run(() => button("Start CSV demo").props.onClick());
    vi.mocked(api.state).mockResolvedValue(loaded);
    const input = renderer.root.findByProps({ id: "csv-file" });
    const event = { currentTarget: { files: [new File(["data"], "sample.csv")], value: "sample.csv" } };
    await run(() => input.props.onChange(event)); expect(event.currentTarget.value).toBe("");
    await run(() => input.props.onChange({ currentTarget: { files: null, value: "" } }));
    await run(() => input.props.onChange({ currentTarget: { files: [], value: "" } }));
    expect(textContent()).toContain("Replace CSV"); expect(textContent()).toContain("Your answer and evidence");
    await run(() => button("What were mobile activations by channel last month?").props.onClick());
    expect(renderer.root.findByType("textarea").props.value).toContain("by channel");
    await run(() => renderer.root.findByType("textarea").props.onChange({ target: { value: "  " } }));
    expect(button("Ask question").props.disabled).toBe(true);
    await run(() => renderer.root.findByType("textarea").props.onChange({ target: { value: "Mobile activations last month" } }));
    await run(() => renderer.root.findByProps({ id: "as-of" }).props.onChange({ target: { value: "2026-08-17" } }));
    const preventDefault = vi.fn();
    vi.mocked(api.state).mockResolvedValue({ ...loaded, last_response: result });
    await run(() => renderer.root.findByType("form").props.onSubmit({ preventDefault }));
    expect(preventDefault).toHaveBeenCalled(); expect(textContent()).toContain("31 activations");
    expect(textContent()).toContain("Execution evidence"); expect(textContent()).toContain("VERIFIED");
    vi.mocked(api.state).mockRejectedValueOnce(new Error("Refresh unavailable"));
    await run(() => button("Refresh state").props.onClick()); expect(textContent()).toContain("Refresh unavailable");
    await run(() => button("Clear data and end session").props.onClick()); expect(textContent()).toContain("Start CSV demo");
  });
  it("disables controls while busy and renders rejected answers without numeric claims", async () => {
    await mount(<><DataSourcePanel session={session} source={null} busy onStart={async () => {}} onUpload={async () => {}} onClear={async () => {}} />
      <ChatPanel ready busy result={{ ...result, answer: null, receipt: null, status: "SOURCE_NOT_READY" }}
        asOf="" onDate={() => {}} onAsk={async () => {}} /></>);
    expect(renderer.root.findByProps({ id: "csv-file" }).props.disabled).toBe(true);
    expect(textContent()).toContain("SOURCE NOT READY"); expect(textContent()).not.toContain("Demonstration data");
  });
  it("hides evidence belonging to another upload and tolerates optional diagnostic fields", async () => {
    await mount(<EvidencePanel state={{ ...loaded, last_response: { ...result, receipt: { ...result.receipt!, source_fingerprint: "other" } } }} />);
    expect(textContent()).not.toContain("Execution evidence");
    await run(() => renderer.update(<EvidencePanel state={{ ...loaded, last_response: { ...result, verification: null, query_ir: null } }} />));
    expect(textContent()).toContain("Execution evidence");
  });
});
