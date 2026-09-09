import { ChatPanel } from "./components/ChatPanel";
import { DataSourcePanel } from "./components/DataSourcePanel";
import { EvidencePanel } from "./components/EvidencePanel";
import { DefinitionPanel } from "./components/DefinitionPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { useWorkspace } from "./hooks/useWorkspace";
import { ConversationPanel } from "./components/ConversationPanel";
import { terminal } from "./lib/runs";

export function App() {
  const workspace = useWorkspace();
  const busy = Boolean(workspace.busy);
  const running = workspace.pending || Boolean(workspace.currentRun && !terminal(workspace.currentRun.status));
  return <div className="app">
    <header className="app-header">
      <div><p className="eyebrow">Talk2Data</p><h1>Data workspace</h1></div>
      <span className="badge">CSV demonstration · {workspace.state?.interpreter === "claude" ? "Claude assisted" : "rules-based"}</span>
    </header>
    <main>
      <div className="workspace-toolbar">
        <p role="status">{workspace.busy || "Internal connections are isolated from this workspace."}</p>
        {workspace.session && <button className="secondary" disabled={busy}
          onClick={() => void workspace.refresh()}>Refresh state</button>}
      </div>
      {workspace.error && <p className="error" role="alert">{workspace.error}</p>}
      <div className="workspace-grid">
        <DataSourcePanel session={workspace.session} source={workspace.state?.source ?? null}
          busy={busy || running} onStart={workspace.start} onUpload={workspace.upload} onClear={workspace.clear} />
        <ChatPanel ready={Boolean(workspace.state?.source) && workspace.state?.definitions?.status !== "REVOKED"} busy={busy || running}
          interpreter={workspace.state?.interpreter ?? "rules"}
          result={workspace.state?.last_response ?? null} asOf={workspace.asOf}
          onDate={workspace.setAsOf} onAsk={workspace.ask} />
        <EvidencePanel state={workspace.state} />
      </div>
      <ConversationPanel sync={workspace.state?.sync ?? null} run={workspace.currentRun} saved={workspace.savedRun}
        pending={workspace.pending} busy={busy} onResume={workspace.refresh} onCancel={workspace.cancelRun} onView={workspace.viewRun} />
      {workspace.session && <div className="definitions-grid">
        <DefinitionPanel view={workspace.state?.definitions ?? null} busy={busy}
          onDraft={workspace.createDraft} onAction={workspace.reviewDraft} onRevoke={workspace.revokeDefinition} />
        <HistoryPanel runs={workspace.state?.history ?? []} result={workspace.historyResult} busy={busy} onRerun={workspace.rerun} />
      </div>}
    </main>
    <footer>CSV data and conversation history belong to this demo session. BigQuery setup is deferred.</footer>
  </div>;
}
