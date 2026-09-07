import { ChatPanel } from "./components/ChatPanel";
import { DataSourcePanel } from "./components/DataSourcePanel";
import { EvidencePanel } from "./components/EvidencePanel";
import { useWorkspace } from "./hooks/useWorkspace";

export function App() {
  const workspace = useWorkspace();
  const busy = Boolean(workspace.busy);
  return <div className="app">
    <header className="app-header">
      <div><p className="eyebrow">Talk2Data</p><h1>Data workspace</h1></div>
      <span className="badge">CSV demonstration · rules-based</span>
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
          busy={busy} onStart={workspace.start} onUpload={workspace.upload} onClear={workspace.clear} />
        <ChatPanel ready={Boolean(workspace.state?.source)} busy={busy}
          result={workspace.state?.last_response ?? null} asOf={workspace.asOf}
          onDate={workspace.setAsOf} onAsk={workspace.ask} />
        <EvidencePanel state={workspace.state} />
      </div>
    </main>
    <footer>Talk2Data foundation release · Demonstration only. No production warehouse access.</footer>
  </div>;
}
