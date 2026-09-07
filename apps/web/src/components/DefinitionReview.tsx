import { useState } from "react";
import type { DefinitionDraft, DraftStatus, ReviewAction } from "../lib/definitions";

const actions: Record<DraftStatus, ReviewAction[]> = {
  DRAFT: ["submit"], IN_REVIEW: ["approve", "reject"], APPROVED: ["publish"], REJECTED: [], PUBLISHED: [],
};
const labels: Record<ReviewAction, string> = {
  submit: "Submit for review", approve: "Approve definition", reject: "Reject draft", publish: "Publish definition",
};

export function DefinitionReview({ draft, busy, onAction }: {
  draft: DefinitionDraft; busy: boolean;
  onAction: (draft: DefinitionDraft, action: ReviewAction, note: string) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  return <article className="definition-review">
    <h3>{draft.edit.name} <span className="definition-status">{draft.status.replaceAll("_", " ")}</span></h3>
    <p>{draft.edit.definition}</p>
    <p className="small">Owner: {draft.edit.owner}. Change: {draft.edit.reason}</p>
    {draft.review_note && <p className="small">Review: {draft.review_note}</p>}
    {actions[draft.status].length > 0 && <>
      <label htmlFor={`review-${draft.draft_id}`}>Review or publication note</label>
      <input id={`review-${draft.draft_id}`} value={note} maxLength={4000} disabled={busy}
        onChange={event => setNote(event.target.value)} />
      <div className="definition-actions">{actions[draft.status].map(action =>
        <button key={action} className={action === "reject" ? "secondary" : ""} disabled={busy || !note.trim()}
          onClick={() => void onAction(draft, action, note.trim())}>{labels[action]}</button>)}</div>
    </>}
  </article>;
}
