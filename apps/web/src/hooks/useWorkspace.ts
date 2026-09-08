import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { ChatResult, DemoSession, WorkspaceState } from "../lib/contracts";
import type { DefinitionDraft, DefinitionEdit, ReviewAction } from "../lib/definitions";
import { checkFile, suggestedAnchor } from "../lib/workspace";
import { runApi, terminal, type RunRequest, type RunSnapshot } from "../lib/runs";

const SESSION_KEY = "talk2data.csv-demo-session.v1";
const PENDING_KEY = "talk2data.csv-pending-run.v1";

export function useWorkspace() {
  const [session, setSession] = useState<DemoSession | null>(null);
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [asOf, setAsOf] = useState("");
  const inFlight = useRef(false);
  const [historyResult, setHistoryResult] = useState<ChatResult | null>(null);
  const [currentRun, setCurrentRun] = useState<RunSnapshot | null>(null);
  const [savedRun, setSavedRun] = useState<RunSnapshot | null>(null);
  const [pending, setPending] = useState(false);
  const watcher = useRef<AbortController | null>(null);

  function forgetPending() { sessionStorage.removeItem(PENDING_KEY); setPending(false); }

  async function track(token: string, run: RunSnapshot) {
    watcher.current?.abort();
    const controller = new AbortController();
    watcher.current = controller;
    const final = await runApi.watch(token, run, controller.signal, setCurrentRun);
    forgetPending();
    setState(await api.state(token));
    if (final.status !== "COMPLETED") setError(final.message);
  }

  async function restoreRun(token: string, snapshot: WorkspaceState) {
    const saved = sessionStorage.getItem(PENDING_KEY);
    if (saved) {
      let value: { token: string; request: RunRequest } | null = null;
      try { value = JSON.parse(saved); } catch { forgetPending(); }
      if (value?.token === token && value.request) {
        setPending(true);
        try { await track(token, await runApi.submit(token, value.request)); }
        catch (failure) {
          if (failure instanceof ApiError && failure.status < 500 && failure.status !== 429) forgetPending();
          throw failure;
        }
        return;
      }
      forgetPending();
    }
    const latest = snapshot.sync?.conversation.latest_run_id;
    if (latest) await track(token, await runApi.get(token, latest));
  }

  useEffect(() => () => watcher.current?.abort(), []);

  async function perform(label: string, operation: () => Promise<void>) {
    if (inFlight.current) return false;
    inFlight.current = true;
    setBusy(label);
    setError("");
    try { await operation(); return true; }
    catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) {
        sessionStorage.removeItem(SESSION_KEY);
        setSession(null);
        setState(null);
        setHistoryResult(null);
        forgetPending(); setCurrentRun(null); setSavedRun(null);
      }
      if (failure instanceof DOMException && failure.name === "AbortError") return false;
      setError(failure instanceof Error ? failure.message : "Something went wrong. Please retry.");
      return false;
    } finally { inFlight.current = false; setBusy(""); }
  }

  async function start() {
    await perform("Opening demo session", async () => {
      const next = await api.createSession();
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(next));
      setSession(next);
      setState(await api.state(next.session_token));
    });
  }

  useEffect(() => {
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (!saved) return;
    let restored: DemoSession;
    try {
      restored = JSON.parse(saved);
      if (typeof restored.session_token !== "string" || !Number.isFinite(restored.maximum_bytes))
        throw new Error("Invalid saved demo session.");
    } catch { sessionStorage.removeItem(SESSION_KEY); return; }
    void perform("Restoring demo session", async () => {
      const snapshot = await api.state(restored.session_token);
      setSession(restored);
      setState(snapshot);
      if (snapshot.source) setAsOf(suggestedAnchor(snapshot.source));
      if (snapshot.sync?.enabled) await restoreRun(restored.session_token, snapshot);
    });
  }, []);

  async function upload(file: File) {
    if (!session) return;
    const issue = checkFile(file, session.maximum_bytes);
    if (issue) { setError(issue); return; }
    await perform("Validating CSV", async () => {
      const source = await api.upload(session.session_token, file);
      // Clear the old answer immediately, even if the following state fetch fails.
      setState(previous => previous ? { ...previous, source, last_response: null } : previous);
      setHistoryResult(null);
      setAsOf(suggestedAnchor(source));
      setState(await api.state(session.session_token));
    });
  }

  async function ask(question: string) {
    if (!session || !state?.source || !asOf) return;
    const fingerprint = state.source.source_fingerprint;
    await perform("Checking definitions and querying CSV", async () => {
      setState(previous => previous ? { ...previous, last_response: null } : previous);
      if (state.sync?.enabled && state.definitions) {
        const request: RunRequest = {
          client_request_id: crypto.randomUUID(), conversation_id: state.sync.conversation.conversation_id,
          expected_revision: state.sync.conversation.revision, question: question.trim(),
          as_of: asOf + "T12:00:00Z", source_fingerprint: fingerprint,
          definition_snapshot_id: state.definitions.snapshot_id,
        };
        sessionStorage.setItem(PENDING_KEY, JSON.stringify({ token: session.session_token, request }));
        setPending(true); setSavedRun(null);
        try { await track(session.session_token, await runApi.submit(session.session_token, request)); }
        catch (failure) {
          if (failure instanceof ApiError && failure.status < 500 && failure.status !== 429) forgetPending();
          throw failure;
        }
        return;
      }
      const result = await api.ask(session.session_token, question.trim(), asOf, fingerprint, state.definitions?.snapshot_id);
      setState(previous => previous && previous.source?.source_fingerprint === fingerprint
        ? { ...previous, last_response: result } : previous);
      setState(await api.state(session.session_token));
    });
  }

  async function refresh() {
    if (!session) return;
    await perform("Refreshing workspace", async () => {
      const snapshot = await api.state(session.session_token);
      setState(snapshot);
      setHistoryResult(null);
      if (snapshot.source && snapshot.source.source_fingerprint !== state?.source?.source_fingerprint)
        setAsOf(suggestedAnchor(snapshot.source));
      if (snapshot.sync?.enabled) await restoreRun(session.session_token, snapshot);
    });
  }

  async function clear() {
    if (!session) return;
    await perform("Clearing demo data", async () => {
      await api.clear(session.session_token);
      sessionStorage.removeItem(SESSION_KEY);
      setSession(null);
      setState(null);
      setAsOf("");
      setHistoryResult(null);
      forgetPending(); setCurrentRun(null); setSavedRun(null);
    });
  }

  async function createDraft(edit: DefinitionEdit) {
    if (!session) return false;
    return perform("Saving definition draft", async () => {
      await api.createDraft(session.session_token, edit);
      setState(await api.state(session.session_token));
    });
  }

  async function reviewDraft(draft: DefinitionDraft, action: ReviewAction, note: string) {
    if (!session) return;
    await perform("Updating definition review", async () => {
      await api.reviewDraft(session.session_token, draft, action, note);
      setState(await api.state(session.session_token));
    });
  }

  async function revokeDefinition(snapshotId: string, revision: number, note: string) {
    if (!session) return;
    await perform("Withdrawing definition publication", async () => {
      await api.revokeDefinition(session.session_token, snapshotId, revision, note);
      setHistoryResult(null);
      setState(await api.state(session.session_token));
    });
  }

  async function rerun(runId: string) {
    if (!session) return;
    await perform("Reproducing a saved answer", async () => {
      setHistoryResult(null);
      setHistoryResult(await api.rerun(session.session_token, runId));
      setState(await api.state(session.session_token));
    });
  }

  async function cancelRun() {
    if (!session || !currentRun || terminal(currentRun.status)) return;
    try {
      const result = await runApi.cancel(session.session_token, currentRun.run_id);
      setCurrentRun(result);
      if (terminal(result.status) && !inFlight.current) {
        forgetPending();
        setState(await api.state(session.session_token));
      }
    }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Cancellation could not be confirmed."); }
  }

  async function viewRun(runId: string) {
    if (!session) return;
    await perform("Loading a saved run", async () => {
      setSavedRun(null);
      setSavedRun(await runApi.get(session.session_token, runId));
    });
  }

  return { session, state, busy, error, asOf, setAsOf, start, upload, ask, refresh, clear,
    createDraft, reviewDraft, revokeDefinition, rerun, historyResult,
    currentRun, savedRun, pending, cancelRun, viewRun };
}
