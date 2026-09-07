export interface Source {
  source_kind: "csv_demo";
  metric_ids: string[];
  dimensions: string[];
  row_count: number;
  coverage_start: string;
  coverage_end: string;
  source_fingerprint: string;
  uploaded_at: string;
}

export interface ChatResult {
  status: string;
  message: string;
  session_id: string;
  answer: null | { headline: string; text: string; caveats: string[] };
  verification: null | { status: string; checks: string[]; failures: string[] };
  receipt: null | {
    receipt_id: string;
    source_kind: string;
    source_fingerprint: string | null;
    result_hash: string;
    result_rows: Record<string, unknown>[];
    row_count: number;
    resolved_start: string;
    resolved_end: string;
    warnings: string[];
  };
  query_ir: null | { semantic_version: string; semantic_snapshot_hash: string; plan_hash: string };
  warnings: string[];
}

export interface WorkspaceState {
  source: Source | null;
  definition: {
    domain_pack_version: string;
    semantic_snapshot_hash: string;
    metric: {
      id: string;
      name: string;
      definition: string;
      semantic_version: string;
      aggregation: string;
      allowed_dimensions: string[];
    };
  };
  last_response: ChatResult | null;
  interpreter: "rules";
  internal_connections_available: false;
}

export interface DemoSession {
  session_token: string;
  maximum_bytes: number;
  maximum_rows: number;
  expires_in_seconds: number;
}
