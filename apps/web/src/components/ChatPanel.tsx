import { useState } from "react";
import type { ChatResult } from "../lib/contracts";
import { languageNames, type LanguageProvider } from "../lib/language";
import { AgentRunPanel } from "./AgentRunPanel";

interface Props {
  ready: boolean;
  busy: boolean;
  result: ChatResult | null;
  asOf: string;
  onDate: (value: string) => void;
  onAsk: (question: string) => Promise<void>;
  interpreter?: LanguageProvider;
}

const EXAMPLES = [
  "What were mobile activations by region last month?",
  "What were mobile activations by channel last month?",
  "What were mobile activations in Northeast yesterday?",
];

export function ChatPanel({ ready, busy, result, asOf, onDate, onAsk, interpreter = "rules" }: Props) {
  const [question, setQuestion] = useState(EXAMPLES[0]);
  return <section className="panel chat-panel" aria-labelledby="chat-heading">
    <p className="eyebrow">02 / Ask your data</p>
    <h2 id="chat-heading">A business question. A traceable answer.</h2>
    <p>This workspace supports Mobile Activations using approved business definitions.
      {interpreter !== "rules" ? ` ${languageNames[interpreter]} interprets your question; governed services query and verify the data.` : " Rules interpret your question; governed services query and verify the data."}</p>
    {interpreter !== "rules" && <p className="small">{`Your question and approved definition metadata are sent to ${languageNames[interpreter]}. CSV rows and query results stay in this workspace.`}</p>}
    {interpreter === "gemini" && <p className="small">Use synthetic demo questions and definitions. Google's free API tier may use submitted content to improve its products.</p>}
    <div className="examples" aria-label="Example questions">
      {EXAMPLES.map(example => <button key={example} className="secondary"
        disabled={busy} onClick={() => setQuestion(example)}>{example}</button>)}
    </div>
    <AgentRunPanel run={result?.agent_run ?? null} />
    <form onSubmit={event => { event.preventDefault(); void onAsk(question); }}>
      <label htmlFor="question">Question</label>
      <textarea id="question" value={question} onChange={event => setQuestion(event.target.value)}
        maxLength={2000} required rows={4} disabled={busy} />
      <div className="form-footer">
        <label htmlFor="as-of">Interpret relative dates as of
          <input id="as-of" type="date" value={asOf} required disabled={busy || !ready}
            onChange={event => onDate(event.target.value)} />
        </label>
        <button disabled={!ready || busy || !question.trim() || !asOf} type="submit">Ask question</button>
      </div>
    </form>
    <div className="answer" aria-live="polite" aria-busy={busy}>
      {!result ? <p>{ready ? "Your answer and evidence will appear here." : "Start a demo session and upload the template to begin."}</p>
        : <>
          <p className="eyebrow">Latest completed run · {result.status.replaceAll("_", " ")}</p>
          {result.answer && <h3>{result.answer.headline}</h3>}
          <p className="answer-text">{result.message}</p>
          {result.answer?.caveats.map(caveat => <p className="small" key={caveat}>{caveat}</p>)}
        </>}
    </div>
    <p className="small">Ask self-contained questions with the metric, grouping and period you need. Saved history keeps each question's original meaning.</p>
  </section>;
}
