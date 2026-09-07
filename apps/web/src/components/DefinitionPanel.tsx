import { useState } from "react";
import type { DefinitionDraft, DefinitionEdit, DefinitionView, ReviewAction } from "../lib/definitions";
import { DefinitionEditor } from "./DefinitionEditor";
import { DefinitionReview } from "./DefinitionReview";

export function DefinitionPanel({ view, busy, onDraft, onAction, onRevoke }: {
  view: DefinitionView | null; busy: boolean;
  onDraft: (edit: DefinitionEdit) => Promise<boolean>;
  onAction: (draft: DefinitionDraft, action: ReviewAction, note: string) => Promise<void>;
  onRevoke: (snapshotId: string, revision: number, note: string) => Promise<void>;
}) {
  const [selected, setSelected] = useState("METRIC:MOBILE_ACTIVATIONS");
  const [editing, setEditing] = useState<DefinitionEdit | null>(null);
  const [withdrawal, setWithdrawal] = useState("");
  if (!view) return null;
  const choices = [
    ...view.metrics.map(record => ({ record, kind: "METRIC" as const })),
    ...view.dimensions.map(record => ({ record, kind: "DIMENSION" as const })),
  ];
  const choice = choices.find(item => `${item.kind}:${item.record.id}` === selected);
  return <section className="panel definitions-panel" aria-labelledby="definitions-heading">
    <p className="eyebrow">04 / Business context</p><h2 id="definitions-heading">Manage business definitions</h2>
    <p>{view.mode === "DEMO_SINGLE_USER" ? "Single user demo: you can try every review step. Internal publishing requires a separate authorized reviewer." : "A different authorized person must approve a submitted definition."}</p>
    <p className="small">Current publication: {view.version} · {view.status}. Effective {view.effective_from}.</p>
    {view.status === "REVOKED" && <p className="error">This publication was withdrawn. Publish a reviewed correction before asking new questions.</p>}
    <label htmlFor="definition-select">Metric or dimension</label>
    <select id="definition-select" value={selected} disabled={busy || Boolean(editing)} onChange={event => setSelected(event.target.value)}>
      {choices.map(item => <option key={`${item.kind}:${item.record.id}`} value={`${item.kind}:${item.record.id}`}>
        {item.kind === "METRIC" ? "Metric" : "Dimension"}: {item.record.name}
      </option>)}
    </select>
    {choice ? <div className="definition-current">
      <h3>{choice.record.name}</h3><p>{choice.record.definition}</p>
      <p className="small">Owner: {choice.record.owner} · Definition version {choice.record.definition_version}</p>
      {!editing && <button disabled={busy} onClick={() => setEditing({ base_snapshot_id: view.snapshot_id,
        kind: choice.kind, definition_id: choice.record.id, name: choice.record.name,
        definition: choice.record.definition, owner: choice.record.owner, aliases: choice.record.aliases, reason: "" })}>
        Propose change
      </button>}
    </div> : <p>No definition is selected.</p>}
    {editing && <DefinitionEditor initial={editing} busy={busy} onSave={onDraft} onClose={() => setEditing(null)} />}
    <h3>Review queue</h3>
    {view.drafts.length === 0 && <p className="small">No proposed changes. Current definitions remain in use until a reviewed draft is published.</p>}
    {view.drafts.map(draft => <DefinitionReview key={draft.draft_id} draft={draft} busy={busy} onAction={onAction} />)}
    <details><summary>Publication history and withdrawal</summary>
      <ol>{view.events.map(event => <li key={event.sequence}>{event.kind}: {event.reason} · effective {event.effective_from}</li>)}</ol>
      <label htmlFor="withdrawal-note">Reason to withdraw the current publication</label>
      <input id="withdrawal-note" value={withdrawal} maxLength={4000} disabled={busy}
        onChange={event => setWithdrawal(event.target.value)} />
      <button className="secondary" disabled={busy || view.status === "REVOKED" || !withdrawal.trim()}
        onClick={() => void onRevoke(view.snapshot_id, view.revision, withdrawal.trim())}>Withdraw publication</button>
    </details>
  </section>;
}
