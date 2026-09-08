import { useState } from "react";
import { AgentRunPanel } from "../components/AgentRunPanel";
import { terminal } from "../lib/runs";
import { useInternalWorkspace } from "./useInternalWorkspace";

export function InternalApp() {
  const workspace = useInternalWorkspace();
  const [question, setQuestion] = useState("");
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const running = Boolean(workspace.run && !terminal(workspace.run.status));
  const blocked = workspace.busy || workspace.pending || running;
  const result = workspace.run?.result;
  return <div className="app">
    <header className="app-header"><div><p className="eyebrow">Talk2Data</p><h1>Business intelligence workspace</h1></div>
      <span className="badge">Internal · {workspace.state?.language.provider === "claude" ? "Claude assisted" : "Governed questions"}</span>
    </header>
    <main>
      {workspace.error && <p className="error" role="alert">{workspace.error}</p>}
      <div className="workspace-toolbar">
        <p role="status">{workspace.state ? `Signed in as ${workspace.state.identity.user_id}` : "Connect through your organization's sign-in gateway."}</p>
        <button disabled={workspace.busy} onClick={() => void workspace.refresh()}>Refresh and resume</button>
      </div>
      {workspace.state && <>
        <div className="workspace-grid">
          <section className="panel"><h2>Conversations</h2>
            <button disabled={blocked} onClick={() => void workspace.create()}>New conversation</button>
            <ul>{workspace.state.conversations.map(item => <li key={item.conversation_id}>
              <button className="secondary" disabled={blocked} onClick={() => void workspace.select(item.conversation_id)}>{item.title}</button>
            </li>)}</ul>
            <p className="small">Your access controls determine which saved conversations are available.</p>
          </section>
          <section className="panel"><h2>Ask a business question</h2>
            <p>Questions use your approved internal connection and current business definitions.</p>
            <form onSubmit={event => { event.preventDefault(); void workspace.ask(question, asOf); }}>
              <label htmlFor="internal-question">Question</label>
              <textarea id="internal-question" required minLength={3} maxLength={2000} rows={4} disabled={blocked}
                value={question} onChange={event => setQuestion(event.target.value)} />
              <label htmlFor="internal-date">Interpret relative dates as of</label>
              <input id="internal-date" type="date" required value={asOf} disabled={blocked}
                onChange={event => setAsOf(event.target.value)} />
              <button type="submit" disabled={blocked || !workspace.history || !question.trim() || !asOf || workspace.state.definitions.status === "REVOKED"}>Ask question</button>
            </form>
            {!workspace.history && <p>Create a conversation to begin.</p>}
            {workspace.pending && <p>Question awaiting confirmation. Resume with its original request identity.</p>}
            {running && <button className="secondary" onClick={() => void workspace.cancel()}>Cancel question</button>}
            <div aria-live="polite"><p>{workspace.run?.message}</p>
              {result?.answer && <h3>{result.answer.headline}</h3>}
              <p>{result?.answer?.text}</p>
              {result?.answer?.caveats.map(caveat => <p className="small" key={caveat}>{caveat}</p>)}
            </div>
            <AgentRunPanel run={workspace.run?.progress ?? null} />
            {result?.receipt && <details><summary>Answer evidence</summary>
              <p>Source: {result.receipt.source_kind} · Verified rows: {result.receipt.row_count}</p>
              <p>Period: {result.receipt.resolved_start} to {result.receipt.resolved_end}</p>
              <p>Verification: {result.verification?.status}</p>
              <p>Definition: {result.semantic_context?.metric.definition}</p>
              <p className="small">Definition publication: {result.semantic_context?.snapshot_id}</p>
            </details>}
          </section>
          <section className="panel"><h2>Live business definitions</h2>
            <p>Publication {workspace.state.definitions.version} · {workspace.state.definitions.status}</p>
            {[...workspace.state.definitions.metrics, ...workspace.state.definitions.dimensions].map(item =>
              <details key={item.id}><summary>{item.name}</summary><p>{item.definition}</p>
                <p className="small">Owner: {item.owner} · Version {item.definition_version}</p></details>)}
          </section>
        </div>
        <section className="panel"><h2>Saved questions</h2>
          <ul>{workspace.history?.runs.map(item => <li key={item.run_id}>
            <button className="secondary" disabled={workspace.busy} onClick={() => void workspace.view(item.run_id)}>{item.question} · {item.status}</button>
          </li>)}</ul>
        </section>
      </>}
    </main>
  </div>;
}
