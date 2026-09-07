import { useState, type FormEvent } from "react";
import type { DefinitionEdit } from "../lib/definitions";

export function DefinitionEditor({ initial, busy, onSave, onClose }: {
  initial: DefinitionEdit; busy: boolean;
  onSave: (edit: DefinitionEdit) => Promise<boolean>; onClose: () => void;
}) {
  const [edit, setEdit] = useState(initial);
  const [aliases, setAliases] = useState(initial.aliases.join(", "));
  const [effective, setEffective] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const saved = await onSave({ ...edit, aliases: aliases.split(",").map(item => item.trim()).filter(Boolean),
      effective_from: effective ? effective + "Z" : undefined });
    if (saved) onClose();
  }
  return <form id="definition-form" className="definition-editor" onSubmit={event => void submit(event)}>
    <h3>Propose a definition change</h3>
    <p className="small">Calculation, source mapping and permissions stay governed separately.</p>
    <label htmlFor="definition-name">Name</label>
    <input id="definition-name" required maxLength={160} value={edit.name} disabled={busy}
      onChange={event => setEdit({ ...edit, name: event.target.value })} />
    <label htmlFor="definition-meaning">Business definition</label>
    <textarea id="definition-meaning" required maxLength={4000} value={edit.definition} disabled={busy}
      onChange={event => setEdit({ ...edit, definition: event.target.value })} />
    <label htmlFor="definition-owner">Business owner</label>
    <input id="definition-owner" required maxLength={160} value={edit.owner} disabled={busy}
      onChange={event => setEdit({ ...edit, owner: event.target.value })} />
    <label htmlFor="definition-aliases">Aliases, separated by commas</label>
    <input id="definition-aliases" value={aliases} disabled={busy} onChange={event => setAliases(event.target.value)} />
    <label htmlFor="definition-reason">Reason for this change</label>
    <textarea id="definition-reason" required maxLength={4000} value={edit.reason} disabled={busy}
      onChange={event => setEdit({ ...edit, reason: event.target.value })} />
    <label htmlFor="definition-effective">Effective at, UTC (optional)</label>
    <input id="definition-effective" type="datetime-local" value={effective} disabled={busy}
      onChange={event => setEffective(event.target.value)} />
    <p className="small">Leave blank to apply on publication. Saving a draft does not change answers.</p>
    <div className="definition-actions">
      <button disabled={busy}>Save draft</button>
      <button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancel edit</button>
    </div>
  </form>;
}
