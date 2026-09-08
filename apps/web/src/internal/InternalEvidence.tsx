import type { ChatResult } from "../lib/contracts";

export function InternalEvidence({ result, currentSnapshot }: { result: ChatResult | null | undefined; currentSnapshot: string }) {
  const receipt = result?.receipt;
  if (!receipt) return null;
  const context = result.semantic_context;
  const columns = [...new Set(receipt.result_rows.flatMap(row => Object.keys(row)))];
  return <details><summary>Answer evidence</summary>
    <p>Source: {receipt.source_kind} · Verified rows: {receipt.row_count}</p>
    <p>Period: {receipt.resolved_start} to {receipt.resolved_end}</p>
    <p>Verification: {result.verification?.status}</p>
    {context && <>
      <h3>Definitions used by this answer</h3>
      {context.snapshot_id !== currentSnapshot && <p className="small">This saved answer uses an earlier publication. New questions use the current business definitions.</p>}
      {[context.metric, ...context.dimensions].map(item => <div key={item.id}>
        <p><strong>{item.name}:</strong> {item.definition}</p>
        <p className="small">Owner: {item.owner} · Definition version {item.definition_version}</p>
      </div>)}
      <p className="hash">Definition publication: {context.snapshot_id}</p>
    </>}
    <div className="result-table" role="region" aria-label="Returned data" tabIndex={0}>
      <table><caption>Returned data</caption>
        <thead><tr>{columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead>
        <tbody>{receipt.result_rows.map((row, index) => <tr key={index}>{columns.map(column => {
          const value = row[column];
          return <td key={column}>{value == null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value)}</td>;
        })}</tr>)}</tbody>
      </table>
    </div>
    <details><summary>Receipt fingerprints</summary><dl>
      <dt>Receipt ID</dt><dd className="hash">{receipt.receipt_id}</dd>
      <dt>Result SHA-256</dt><dd className="hash">{receipt.result_hash}</dd>
    </dl></details>
  </details>;
}
