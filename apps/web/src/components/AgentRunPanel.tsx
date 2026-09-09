import type { AgentRun } from "../lib/contracts";
import { languageNames } from "../lib/language";

const labels: Record<string, string> = {
  SEMANTIC_RESOLVER: "Understand the question",
  QUERY_PLANNER: "Plan the governed query",
  QUERY_EXECUTOR: "Read the selected data",
  RESULT_VERIFIER: "Check the result",
  ANSWER_COMPOSER: "Prepare the answer",
};

export function AgentRunPanel({ run }: { run: AgentRun | null }) {
  if (!run) return null;
  return <details className="agent-run">
    <summary>How this answer was prepared</summary>
    <p className="small">Interpretation: {run.provider !== "rules" ? `${languageNames[run.provider]} assisted` : "Rules"}.
      {run.replayed_interpretation && " Saved interpretation reused; no new model call."}</p>
    <ol>{run.steps.map(step => <li key={step.sequence}>
      {labels[step.role] ?? step.role}: {step.status.toLowerCase()}
    </li>)}</ol>
    {run.provider !== "rules" && <p className="small">
      Model calls: {run.usage.model_calls}. Recorded tokens: {run.usage.input_tokens} in, {run.usage.output_tokens} out.
      {!run.usage.usage_complete && " Usage for an unsuccessful attempt may be missing."}
    </p>}
  </details>;
}
