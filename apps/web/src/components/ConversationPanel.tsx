import { AgentRunPanel } from "./AgentRunPanel";
import { terminal, type RunSnapshot, type SyncState } from "../lib/runs";

interface Props {
  sync: SyncState | null;
  run: RunSnapshot | null;
  saved: RunSnapshot | null;
  pending: boolean;
  busy: boolean;
  onResume: () => Promise<void>;
  onCancel: () => Promise<void>;
  onView: (id: string) => Promise<void>;
}

export function ConversationPanel({ sync, run, saved, pending, busy, onResume, onCancel, onView }: Props) {
  if (!sync) return null;
  const active = Boolean(run && !terminal(run.status));
  return <section className="panel" aria-labelledby="conversation-heading">
    <p className="eyebrow">Conversation</p><h2 id="conversation-heading">Questions and progress</h2>
    <p className="small">{sync.durable
      ? "This workspace can be restored after a service restart until the session expires or is cleared."
      : "This workspace is temporary and will be lost if the service restarts."}</p>
    {run && <><p role="status">{run.status.replaceAll("_", " ")}: {run.message}</p>
      <AgentRunPanel run={run.progress} /></>}
    {active && <button className="secondary" disabled={run?.status === "CANCELLATION_REQUESTED"}
      onClick={() => void onCancel()}>Cancel question</button>}
    {(active || pending) && !busy && <button onClick={() => void onResume()}>Resume progress</button>}
    <ol>{[...sync.runs].reverse().map(item => <li key={item.run_id}>
      <button className="secondary" disabled={busy} onClick={() => void onView(item.run_id)}>{item.question}</button>
      <span className="small"> {item.status.replaceAll("_", " ")}</span>
    </li>)}</ol>
    {saved && <div className="answer"><h3>Saved question</h3><p>{saved.request.question}</p>
      <p className="small">Original source: {saved.source_binding.slice(0, 12)} · Original date: {saved.request.as_of.slice(0, 10)}</p>
      <p>{saved.result?.message ?? saved.message}</p><AgentRunPanel run={saved.progress} /></div>}
  </section>;
}
