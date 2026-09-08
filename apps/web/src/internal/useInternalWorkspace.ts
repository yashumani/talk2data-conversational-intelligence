import { useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { terminal } from "../lib/runs";
import { internalApi, type History, type InternalRequest, type InternalRun } from "./api";

const pendingKey = "talk2data.internal.pending.v1";
type Workspace = Awaited<ReturnType<typeof internalApi.load>>;
interface Pending { scope: string; binding: string; request: InternalRequest }

export function useInternalWorkspace() {
  const [state, setState] = useState<Workspace | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [run, setRun] = useState<InternalRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const alive = useRef(true);
  const pendingRequest = useRef<Pending | null>(null);

  async function action(operation: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try { await operation(); }
    catch (failure) {
      if (!alive.current) return;
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) {
        controller.current?.abort(); setState(null); setHistory(null); setRun(null);
        pendingRequest.current = null; sessionStorage.removeItem(pendingKey); setPending(false);
      }
      setError(failure instanceof Error ? failure.message : "The workspace could not complete this request.");
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  async function follow(value: InternalRun, workspace: Workspace) {
    if (value.source_binding !== workspace.identity.source_binding)
      throw new ApiError(409, "The approved data connection changed. Refresh the workspace.");
    controller.current?.abort();
    const active = new AbortController(); controller.current = active;
    const result = await internalApi.watch(value, active.signal, value => { if (alive.current) setRun(value); });
    if (alive.current) {
      setRun(result);
      setHistory(await internalApi.history(result.request.conversation_id));
    }
  }

  async function refresh() {
    await action(async () => {
      const workspace = await internalApi.load();
      if (!alive.current) return;
      setState(workspace);
      const raw = sessionStorage.getItem(pendingKey);
      const saved: Pending | null = pendingRequest.current || (raw ? JSON.parse(raw) as Pending : null);
      if (saved) {
        if (saved.scope !== workspace.identity.scope_id || saved.binding !== workspace.identity.source_binding) {
          sessionStorage.removeItem(pendingKey); pendingRequest.current = null; setPending(false);
          throw new ApiError(409, "The signed identity, access scope or data connection changed. The pending request was not resent.");
        }
        pendingRequest.current = saved; setPending(true);
        const admitted = await internalApi.submit(saved.request);
        sessionStorage.removeItem(pendingKey); pendingRequest.current = null; setPending(false);
        await follow(admitted, workspace);
      } else if (workspace.conversations.length) {
        const item = await internalApi.history(workspace.conversations[0].conversation_id);
        setHistory(item);
        if (item.conversation.latest_run_id) await follow(await internalApi.get(item.conversation.latest_run_id), workspace);
      } else { setHistory(null); setRun(null); }
    });
  }

  useEffect(() => {
    alive.current = true; void refresh();
    return () => { alive.current = false; controller.current?.abort(); };
  }, []);

  async function create() {
    await action(async () => {
      const conversation = await internalApi.create();
      setHistory({ conversation, runs: [] }); setRun(null);
      setState(await internalApi.load());
    });
  }
  async function select(id: string) {
    await action(async () => {
      const workspace = await internalApi.load();
      setState(workspace);
      const selected = await internalApi.history(id); setHistory(selected); setRun(null);
      if (selected.conversation.latest_run_id) await follow(await internalApi.get(selected.conversation.latest_run_id), workspace);
    });
  }
  async function ask(question: string, asOf: string) {
    if (!state || !history || pending || (run && !terminal(run.status))) return;
    await action(async () => {
      const request: InternalRequest = { client_request_id: crypto.randomUUID(),
        conversation_id: history.conversation.conversation_id, expected_revision: history.conversation.revision,
        question: question.trim(), as_of: asOf + "T12:00:00Z", definition_snapshot_id: state.definitions.snapshot_id };
      const record: Pending = { scope: state.identity.scope_id, binding: state.identity.source_binding, request };
      // Persist before POST so lost acknowledgement cannot create a second warehouse/model execution.
      sessionStorage.setItem(pendingKey, JSON.stringify(record)); pendingRequest.current = record; setPending(true);
      const admitted = await internalApi.submit(request);
      sessionStorage.removeItem(pendingKey); pendingRequest.current = null; setPending(false);
      await follow(admitted, state);
    });
  }
  async function cancel() {
    if (!run || terminal(run.status)) return;
    // Cancellation must remain available while the progress stream owns the ordinary UI lock.
    try { setRun(await internalApi.cancel(run.run_id)); }
    catch { controller.current?.abort(); setRun(null); setHistory(null); setState(null); setError("Cancellation could not be confirmed. Refresh your signed session."); }
  }
  async function view(id: string) {
    await action(async () => { if (state) await follow(await internalApi.get(id), state); });
  }
  return { state, history, run, busy, pending, error, refresh, create, select, ask, cancel, view };
}
