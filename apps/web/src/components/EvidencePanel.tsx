import type { WorkspaceState } from "../lib/contracts";
import { matchesSource } from "../lib/workspace";

export function EvidencePanel({ state }: { state: WorkspaceState | null }) {
  const definition = state?.definition;
  const result = state?.last_response;
  const receipt = matchesSource(result ?? null, state?.source ?? null) ? result?.receipt : null;
  return <section className="panel evidence-panel" aria-labelledby="evidence-heading">
    <p className="eyebrow">03 / Definitions & evidence</p>
    <h2 id="evidence-heading">Know what was used</h2>
    {definition ? <>
      <h3>{definition.metric.name}</h3>
      <p>{definition.metric.definition}</p>
      <dl>
        <dt>Metric version</dt><dd>{definition.metric.semantic_version}</dd>
        <dt>Definition pack</dt><dd>{definition.domain_pack_version}</dd>
        <dt>Aggregation</dt><dd>{definition.metric.aggregation}</dd>
      </dl>
      <p className="small">Definitions are the packaged approved snapshot. Live approval and refresh workflow is planned.</p>
    </> : <p>Start a demo session to inspect its approved metric definition.</p>}
    {receipt ? <>
      <h3>Execution evidence</h3>
      <dl>
        <dt>Verification</dt><dd>{result?.verification?.status}</dd>
        <dt>Source</dt><dd>Uploaded CSV only</dd>
        <dt>Period</dt><dd>{receipt.resolved_start} — {receipt.resolved_end}</dd>
        <dt>Result rows</dt><dd>{receipt.row_count}</dd>
      </dl>
      <details><summary>Source and query fingerprints</summary><dl>
        <dt>CSV SHA-256</dt><dd className="hash">{receipt.source_fingerprint}</dd>
        <dt>Result SHA-256</dt><dd className="hash">{receipt.result_hash}</dd>
        <dt>Receipt ID</dt><dd className="hash">{receipt.receipt_id}</dd>
        <dt>Semantic snapshot</dt><dd className="hash">{result?.query_ir?.semantic_snapshot_hash}</dd>
      </dl></details>
      <details><summary>Returned data</summary>
        <pre>{JSON.stringify(receipt.result_rows, null, 2)}</pre>
      </details>
    </> : <p className="small">No matching execution receipt yet. Rejected or incomplete requests do not produce numeric answers.</p>}
    <p className="small">Verification checks query lineage and arithmetic. It does not independently certify the uploaded business data.</p>
  </section>;
}
