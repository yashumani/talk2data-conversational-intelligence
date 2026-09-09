import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { App } from "./App";
import { DefinitionPanel } from "./components/DefinitionPanel";
import { DefinitionReview } from "./components/DefinitionReview";
import { HistoryPanel } from "./components/HistoryPanel";
import { EvidencePanel } from "./components/EvidencePanel";
import { AgentRunPanel } from "./components/AgentRunPanel";
import { useWorkspace } from "./hooks/useWorkspace";
import { api, ApiError } from "./lib/api";
import type { AgentRun, ChatResult, DemoSession, Source, WorkspaceState } from "./lib/contracts";
import type { DefinitionDraft, DefinitionEdit, DefinitionView, DraftStatus } from "./lib/definitions";

const metric = { id: "MOBILE_ACTIVATIONS", name: "Mobile Activations", definition: "Completed new connections",
  owner: "Demo Sales", definition_version: 1, aliases: ["activations"] };
const dimension = { ...metric, id: "REGION", name: "Region", definition: "Sales reporting territory", aliases: [] };
const definitions: DefinitionView = { revision: 1, mode: "DEMO_SINGLE_USER", snapshot_id: "b".repeat(64),
  version: "1", effective_from: "2026-01-01T00:00:00Z", status: "PUBLISHED",
  metrics: [metric], dimensions: [dimension], drafts: [], events: [] };
const edit: DefinitionEdit = { base_snapshot_id: definitions.snapshot_id, kind: "METRIC", definition_id: metric.id,
  name: metric.name, definition: metric.definition, owner: metric.owner, aliases: metric.aliases, reason: "Clarify meaning" };
const draft: DefinitionDraft = { draft_id: "draft/1", revision: 1, status: "DRAFT", edit, review_note: null };
const session: DemoSession = { session_token: "token", maximum_bytes: 2_000_000, maximum_rows: 20_000, expires_in_seconds: 1800 };
const source: Source = { source_kind: "csv_demo", metric_ids: [metric.id], dimensions: ["REGION"], row_count: 31,
  coverage_start: "2026-07-01", coverage_end: "2026-07-31", source_fingerprint: "a".repeat(64), uploaded_at: "2026-08-01T00:00:00Z" };
const result: ChatResult = { status: "ANSWERED", message: "31 activations", session_id: "s", warnings: [],
  answer: { headline: "Activations", text: "31 activations", caveats: [] }, verification: null, query_ir: null,
  receipt: { receipt_id: "receipt", source_kind: "csv_demo", source_fingerprint: source.source_fingerprint,
    result_hash: "r", result_rows: [{ value: 31 }], row_count: 1, resolved_start: "2026-07-01", resolved_end: "2026-07-31", warnings: [] },
  semantic_context: { snapshot_id: definitions.snapshot_id, publication_sequence: 0, effective_from: definitions.effective_from,
    metric, dimensions: [dimension] } };
const saved = { run_id: "run/1", question: "Mobile activations last month?", snapshot_id: definitions.snapshot_id,
  source_fingerprint: source.source_fingerprint };
const loaded: WorkspaceState = { source, last_response: null, definitions, history: [],
  interpreter: "rules", internal_connections_available: false, definition: { metric: { ...metric,
    semantic_version: "2", aggregation: "SUM", allowed_dimensions: ["REGION"] }, domain_pack_version: "1", semantic_snapshot_hash: "b" } };
let renderer: ReactTestRenderer;
let hook: ReturnType<typeof useWorkspace>;
const stored = new Map<string, string>();
const key = "talk2data.csv-demo-session.v1";
function Probe() { hook = useWorkspace(); return null; }
async function run(operation: () => unknown) { await act(async () => { await operation(); }); }
async function mount(element = <Probe />) { await run(() => { renderer = create(element); }); }
function button(label: string) { return renderer.root.findAllByType("button").find(node => node.children.join("") === label)!; }
function change(id: string, value: string) { return run(() => renderer.root.findByProps({ id }).props.onChange({ target: { value } })); }
function rendered() { return JSON.stringify(renderer.toJSON()); }
const onDraft = vi.fn(async (_: DefinitionEdit) => true);
const onAction = vi.fn(async () => {});
const onRevoke = vi.fn(async () => {});
function panel(view: DefinitionView | null = definitions, busy = false) {
  return <DefinitionPanel view={view} busy={busy} onDraft={onDraft} onAction={onAction} onRevoke={onRevoke} />;
}

beforeEach(() => {
  stored.clear(); vi.clearAllMocks();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("sessionStorage", { getItem: (k: string) => stored.get(k) ?? null,
    setItem: (k: string, v: string) => stored.set(k, v), removeItem: (k: string) => stored.delete(k) });
  vi.spyOn(api, "createSession").mockResolvedValue(session);
  vi.spyOn(api, "state").mockResolvedValue(loaded);
  vi.spyOn(api, "ask").mockResolvedValue(result);
  vi.spyOn(api, "upload").mockResolvedValue(source);
  vi.spyOn(api, "clear").mockResolvedValue(undefined);
  vi.spyOn(api, "createDraft").mockResolvedValue(draft);
  vi.spyOn(api, "reviewDraft").mockResolvedValue({ ...draft, revision: 2, status: "IN_REVIEW" });
  vi.spyOn(api, "revokeDefinition").mockResolvedValue(undefined);
  vi.spyOn(api, "rerun").mockResolvedValue(result);
});
afterEach(async () => { if (renderer) await run(() => renderer.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("edits metric and dimension metadata, schedules publication, and keeps failed saves editable", async () => {
  await mount(panel(null)); expect(renderer.toJSON()).toBeNull();
  await run(() => renderer.update(panel()));
  expect(rendered()).toContain("Single user demo");
  await run(() => button("Propose change").props.onClick());
  expect(renderer.root.findByProps({ id: "definition-select" }).props.disabled).toBe(true);
  await change("definition-name", "Approved activations");
  await change("definition-meaning", "Completed connections in the reporting period");
  await change("definition-owner", "Sales Operations");
  await change("definition-aliases", " connections, , customer starts ");
  await change("definition-reason", "Make the business meaning precise");
  await change("definition-effective", "2026-10-01T00:00");
  onDraft.mockResolvedValueOnce(false);
  const preventDefault = vi.fn();
  await run(() => renderer.root.findByProps({ id: "definition-form" }).props.onSubmit({ preventDefault }));
  expect(preventDefault).toHaveBeenCalled(); expect(button("Save draft")).toBeDefined();
  expect(onDraft).toHaveBeenLastCalledWith({ ...edit, name: "Approved activations",
    definition: "Completed connections in the reporting period", owner: "Sales Operations",
    aliases: ["connections", "customer starts"], reason: "Make the business meaning precise", effective_from: "2026-10-01T00:00Z" });
  await run(() => renderer.root.findByProps({ id: "definition-form" }).props.onSubmit({ preventDefault }));
  expect(renderer.root.findAllByProps({ id: "definition-form" })).toHaveLength(0);
  await change("definition-select", "DIMENSION:REGION");
  await run(() => button("Propose change").props.onClick());
  await change("definition-reason", "Clarify territory");
  await run(() => renderer.root.findByProps({ id: "definition-form" }).props.onSubmit({ preventDefault }));
  expect(onDraft).toHaveBeenLastCalledWith(expect.objectContaining({ kind: "DIMENSION", definition_id: "REGION", effective_from: undefined }));
  await run(() => button("Propose change").props.onClick());
  await run(() => button("Cancel edit").props.onClick());
  await change("definition-select", "METRIC:UNKNOWN");
  expect(rendered()).toContain("No definition is selected.");
});

it("makes review stages and withdrawal explicit, disables busy operations, and displays events", async () => {
  const statuses: DraftStatus[] = ["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "PUBLISHED"];
  const queued = statuses.map((status, index) => ({ ...draft, draft_id: String(index), status, review_note: index ? "Reviewed meaning" : null }));
  await mount(panel({ ...definitions, mode: "SEPARATE_REVIEWER", drafts: queued,
    events: [{ sequence: 1, kind: "PUBLISHED", reason: "Clarified territory", effective_from: "2026-08-01T00:00:00Z" }] }));
  expect(rendered()).toContain("different authorized person"); expect(rendered()).toContain("Clarified territory");
  expect(button("Withdraw publication").props.disabled).toBe(true);
  const labels = [["Submit for review", "submit", "0"], ["Approve definition", "approve", "1"],
    ["Reject draft", "reject", "1"], ["Publish definition", "publish", "2"]];
  for (const [label, action, id] of labels) {
    expect(button(label).props.disabled).toBe(true);
    await change("review-" + id, "  Checked against source  ");
    await run(() => button(label).props.onClick());
    expect(onAction).toHaveBeenLastCalledWith(queued[Number(id)], action, "Checked against source");
    await change("review-" + id, "");
  }
  await change("withdrawal-note", "  Incorrect business definition  ");
  await run(() => button("Withdraw publication").props.onClick());
  expect(onRevoke).toHaveBeenCalledWith(definitions.snapshot_id, 1, "Incorrect business definition");
  await run(() => renderer.update(panel({ ...definitions, status: "REVOKED" })));
  expect(rendered()).toContain("Publish a reviewed correction");
  expect(button("Withdraw publication").props.disabled).toBe(true);
  await run(() => renderer.update(panel(definitions, true)));
  expect(button("Propose change").props.disabled).toBe(true);
  await run(() => renderer.update(panel()));
  await run(() => button("Propose change").props.onClick());
  await run(() => renderer.update(panel(definitions, true)));
  expect(renderer.root.findByProps({ id: "definition-owner" }).props.disabled).toBe(true);
  await run(() => renderer.update(<DefinitionReview draft={draft} busy onAction={onAction} />));
  expect(button("Submit for review").props.disabled).toBe(true);
});

it("renders saved answers independently of the selected source and cites earlier definitions", async () => {
  const onRerun = vi.fn(async () => {});
  await mount(<HistoryPanel runs={[]} result={null} busy={false} onRerun={onRerun} />);
  expect(rendered()).toContain("No saved answers");
  await run(() => renderer.update(<HistoryPanel runs={[saved]} result={result} busy={false} onRerun={onRerun} />));
  await run(() => button("Re-run saved answer").props.onClick());
  expect(onRerun).toHaveBeenCalledWith(saved.run_id); expect(rendered()).toContain("Definition version");
  await run(() => renderer.update(<HistoryPanel runs={[saved]} result={{ ...result, answer: null, semantic_context: undefined }} busy onRerun={onRerun} />));
  expect(rendered()).toContain(result.message); expect(button("Re-run saved answer").props.disabled).toBe(true);
  await run(() => renderer.update(<EvidencePanel state={{ ...loaded, last_response: result }} />));
  expect(rendered()).toContain("Definition used by this answer"); expect(rendered()).toContain(dimension.definition);
  expect(rendered()).not.toContain("earlier publication");
  await run(() => renderer.update(<EvidencePanel state={{ ...loaded, definitions: { ...definitions, snapshot_id: "new" }, last_response: result }} />));
  expect(rendered()).toContain("earlier publication");
});

it("synchronizes review, publication and history while binding new questions to the visible snapshot", async () => {
  await mount();
  expect(await hook.createDraft(edit)).toBe(false);
  await run(() => hook.reviewDraft(draft, "submit", "Review"));
  await run(() => hook.revokeDefinition("id", 1, "Withdraw"));
  await run(() => hook.rerun("id"));
  expect(api.reviewDraft).not.toHaveBeenCalled();
  await run(() => hook.start()); await run(() => hook.setAsOf("2026-08-01"));
  vi.mocked(api.state).mockResolvedValue({ ...loaded, last_response: result, history: [saved] });
  await run(() => hook.ask("  Mobile activations last month? "));
  expect(api.ask).toHaveBeenCalledWith("token", "Mobile activations last month?", "2026-08-01", source.source_fingerprint, definitions.snapshot_id);
  expect(hook.state?.history).toEqual([saved]);
  await run(() => hook.createDraft(edit)); expect(api.createDraft).toHaveBeenCalledWith("token", edit);
  await run(() => hook.reviewDraft(draft, "submit", "Ready")); expect(api.reviewDraft).toHaveBeenCalledWith("token", draft, "submit", "Ready");
  await run(() => hook.rerun(saved.run_id)); expect(hook.historyResult).toEqual(result);
  vi.mocked(api.state).mockResolvedValue({ ...loaded, last_response: null, definitions: { ...definitions, status: "REVOKED", revision: 5 } });
  await run(() => hook.revokeDefinition(definitions.snapshot_id, 4, "Wrong meaning"));
  expect(api.revokeDefinition).toHaveBeenCalledWith("token", definitions.snapshot_id, 4, "Wrong meaning");
  expect(hook.historyResult).toBeNull(); expect(hook.state?.definitions?.status).toBe("REVOKED");
});

it("preserves review input on conflicts and clears saved output on expiry", async () => {
  stored.set(key, JSON.stringify(session)); await mount();
  vi.mocked(api.createDraft).mockRejectedValueOnce(new ApiError(409, "Refresh definitions"));
  let savedDraft = true;
  await run(async () => { savedDraft = await hook.createDraft(edit); });
  expect(savedDraft).toBe(false); expect(hook.error).toBe("Refresh definitions");
  await run(() => hook.rerun(saved.run_id)); expect(hook.historyResult).toEqual(result);
  vi.mocked(api.rerun).mockRejectedValueOnce(new ApiError(409, "Snapshot withdrawn"));
  await run(() => hook.rerun(saved.run_id));
  expect(hook.historyResult).toBeNull(); expect(hook.error).toBe("Snapshot withdrawn");
  await run(() => hook.rerun(saved.run_id));
  vi.mocked(api.reviewDraft).mockRejectedValueOnce(new ApiError(401, "Expired"));
  await run(() => hook.reviewDraft(draft, "submit", "Ready"));
  expect(hook.session).toBeNull(); expect(hook.historyResult).toBeNull();
});

it("wires the definition and history panels into the application and disables revoked queries", async () => {
  stored.set(key, JSON.stringify(session));
  vi.mocked(api.state).mockResolvedValue({ ...loaded, definitions: { ...definitions, status: "REVOKED" }, history: [saved] });
  await mount(<App />);
  expect(rendered()).toContain("Not configured"); expect(button("Ask question").props.disabled).toBe(true);
  await run(() => button("Re-run saved answer").props.onClick());
  expect(rendered()).toContain("Reproduced answer");
  await run(() => button("Propose change").props.onClick());
  await change("definition-reason", "Correct withdrawn publication");
  await run(() => renderer.root.findByProps({ id: "definition-form" }).props.onSubmit({ preventDefault: vi.fn() }));
  expect(api.createDraft).toHaveBeenCalled();
});

it("distinguishes configured Claude, governed stages and saved interpretation replay", async () => {
  const trace: AgentRun = { status: "ANSWERED", provider: "claude", model: "claude-contract-test",
    replayed_interpretation: false, steps: [{ role: "SEMANTIC_RESOLVER", sequence: 1, status: "SUCCEEDED" }],
    usage: { model_calls: 1, input_tokens: 1000, output_tokens: 80, usage_complete: true } };
  stored.set(key, JSON.stringify(session));
  vi.mocked(api.state).mockResolvedValue({ ...loaded, interpreter: "claude", last_response: { ...result, agent_run: trace } });
  await mount(<App />);
  expect(rendered()).toContain("Claude assisted");
  expect(rendered()).toContain("Your question and approved definition metadata are sent to Claude");
  expect(rendered()).toContain("Understand the question");
  expect(rendered()).not.toContain("unsuccessful attempt may be missing");
  await run(() => renderer.update(<AgentRunPanel run={{ ...trace, replayed_interpretation: true,
    steps: [{ role: "FUTURE_STAGE", sequence: 1, status: "SUCCEEDED" }],
    usage: { ...trace.usage, model_calls: 0, usage_complete: false } }} />));
  expect(rendered()).toContain("Saved interpretation reused");
  expect(rendered()).toContain("FUTURE_STAGE"); expect(rendered()).toContain("unsuccessful attempt may be missing");
  await run(() => renderer.update(<AgentRunPanel run={{ ...trace, provider: "rules", model: null }} />));
  expect(rendered()).toContain("Rules"); expect(rendered()).not.toContain("Recorded tokens");
  await run(() => renderer.update(<HistoryPanel runs={[saved]} result={{ ...result, agent_run: trace }} busy={false} onRerun={async () => {}} />));
  expect(rendered()).toContain("How this answer was prepared");
});

it("removes an earlier answer while a new provider request fails", async () => {
  stored.set(key, JSON.stringify(session));
  vi.mocked(api.state).mockResolvedValue({ ...loaded, interpreter: "claude", last_response: result });
  await mount();
  vi.mocked(api.ask).mockRejectedValue(new ApiError(503, "Claude unavailable"));
  await run(() => hook.ask("Mobile activations last month?"));
  expect(hook.state?.last_response).toBeNull();
  expect(hook.error).toBe("Claude unavailable");
});
