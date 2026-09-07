export interface DefinitionRecord {
  id: string;
  name: string;
  definition: string;
  owner: string;
  definition_version: number;
  aliases: string[];
}

export interface DefinitionEdit {
  base_snapshot_id: string;
  kind: "METRIC" | "DIMENSION";
  definition_id: string;
  name: string;
  definition: string;
  owner: string;
  aliases: string[];
  reason: string;
  effective_from?: string;
}

export type ReviewAction = "submit" | "approve" | "reject" | "publish";
export type DraftStatus = "DRAFT" | "IN_REVIEW" | "APPROVED" | "REJECTED" | "PUBLISHED";
export interface DefinitionDraft {
  draft_id: string;
  revision: number;
  status: DraftStatus;
  edit: DefinitionEdit;
  review_note: string | null;
}

export interface DefinitionView {
  revision: number;
  mode: "DEMO_SINGLE_USER" | "SEPARATE_REVIEWER";
  snapshot_id: string;
  version: string;
  effective_from: string;
  status: "PUBLISHED" | "REVOKED";
  metrics: DefinitionRecord[];
  dimensions: DefinitionRecord[];
  drafts: DefinitionDraft[];
  events: { sequence: number; kind: string; reason: string; effective_from: string }[];
}

export interface SavedRun {
  run_id: string;
  question: string;
  snapshot_id: string;
  source_fingerprint: string;
}
