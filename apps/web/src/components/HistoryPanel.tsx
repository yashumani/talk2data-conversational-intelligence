import type { ChatResult } from "../lib/contracts";
import type { SavedRun } from "../lib/definitions";
import { AgentRunPanel } from "./AgentRunPanel";

export function HistoryPanel({ runs, result, busy, onRerun }: {
  runs: SavedRun[]; result: ChatResult | null; busy: boolean; onRerun: (runId: string) => Promise<void>;
}) {
  return <section className="panel" aria-labelledby="history-heading">
    <p className="eyebrow">05 / Reproducibility</p><h2 id="history-heading">Saved answers</h2>
    <p className="small">The latest four successful runs retain their CSV and definition snapshot for this demo session.</p>
    {runs.length === 0 && <p>No saved answers yet.</p>}
    {runs.map(run => <article className="saved-run" key={run.run_id}>
      <p>{run.question}</p><p className="small">Definition reference: {run.snapshot_id.slice(0, 12)}</p>
      <button className="secondary" disabled={busy} onClick={() => void onRerun(run.run_id)}>Re-run saved answer</button>
    </article>)}
    {result && <div className="reproduced-answer" role="status">
      <h3>Reproduced answer</h3>
      <p className="small">Uses the saved CSV and definitions. Your current CSV selection is preserved.</p>
      <p>{result.answer?.text ?? result.message}</p>
      {result.semantic_context && <p className="small">{result.semantic_context.metric.name} · Definition version {result.semantic_context.metric.definition_version}</p>}
      <AgentRunPanel run={result.agent_run ?? null} />
    </div>}
  </section>;
}
