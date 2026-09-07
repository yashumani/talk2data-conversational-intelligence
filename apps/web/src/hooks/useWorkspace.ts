import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { DemoSession, WorkspaceState } from "../lib/contracts";
import { checkFile, suggestedAnchor } from "../lib/workspace";

const SESSION_KEY = "talk2data.csv-demo-session.v1";

export function useWorkspace() {
  const [session, setSession] = useState<DemoSession | null>(null);
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [asOf, setAsOf] = useState("");
  const inFlight = useRef(false);

  async function perform(label: string, operation: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(label);
    setError("");
    try { await operation(); }
    catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) {
        sessionStorage.removeItem(SESSION_KEY);
        setSession(null);
        setState(null);
      }
      setError(failure instanceof Error ? failure.message : "Something went wrong. Please retry.");
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
      setAsOf(suggestedAnchor(source));
      setState(await api.state(session.session_token));
    });
  }

  async function ask(question: string) {
    if (!session || !state?.source || !asOf) return;
    const fingerprint = state.source.source_fingerprint;
    await perform("Checking definitions and querying CSV", async () => {
      const result = await api.ask(session.session_token, question.trim(), asOf, fingerprint);
      setState(previous => previous && previous.source?.source_fingerprint === fingerprint
        ? { ...previous, last_response: result } : previous);
    });
  }

  async function refresh() {
    if (!session) return;
    await perform("Refreshing workspace", async () => {
      const snapshot = await api.state(session.session_token);
      setState(snapshot);
      if (snapshot.source && snapshot.source.source_fingerprint !== state?.source?.source_fingerprint)
        setAsOf(suggestedAnchor(snapshot.source));
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
    });
  }

  return { session, state, busy, error, asOf, setAsOf, start, upload, ask, refresh, clear };
}
