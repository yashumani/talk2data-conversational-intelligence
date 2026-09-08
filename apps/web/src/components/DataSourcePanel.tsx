import type { DemoSession, Source } from "../lib/contracts";

interface Props {
  session: DemoSession | null;
  source: Source | null;
  busy: boolean;
  onStart: () => Promise<void>;
  onUpload: (file: File) => Promise<void>;
  onClear: () => Promise<void>;
}

export function DataSourcePanel({ session, source, busy, onStart, onUpload, onClear }: Props) {
  return <section className="panel" aria-labelledby="source-heading">
    <p className="eyebrow">01 / Data connection</p>
    <h2 id="source-heading">Your demo source</h2>
    <p>Upload synthetic or explicitly approved demonstration data only.</p>
    <div className="connection selected">
      <strong>CSV demonstration</strong>
      <span>{source ? "Connected to this session" : "Optional · no warehouse required"}</span>
    </div>
    <div className="connection">
      <strong>BigQuery · internal</strong>
      <span>Not configured · connection placeholders ready. Live validation deferred.</span>
    </div>
    {!session ? <button disabled={busy} onClick={() => void onStart()}>Start CSV demo</button> : <>
      <label className="upload-label" htmlFor="csv-file">{source ? "Replace CSV" : "Choose a CSV file"}</label>
      <input id="csv-file" type="file" accept=".csv,text/csv" disabled={busy}
        onChange={event => {
          const file = event.currentTarget.files?.[0];
          if (file) void onUpload(file);
          event.currentTarget.value = "";
        }} />
      <p className="small">Up to {session.maximum_rows.toLocaleString()} rows and{" "}
        {(session.maximum_bytes / 1_000_000).toFixed(1)} MB. Session expires after{" "}
        {Math.floor(session.expires_in_seconds / 60)} minutes.</p>
    </>}
    <a className="text-link" href={import.meta.env.BASE_URL + "samples/mobile-activations.csv"} download>
      Download synthetic CSV template
    </a>
    <p className="small">Template fields: date, region, channel, activations. Optional: market, store, plan.
      Daily observations; missing dates are not zero.</p>
    {source && <dl>
      <dt>Rows</dt><dd>{source.row_count.toLocaleString()}</dd>
      <dt>Coverage</dt><dd>{source.coverage_start} — {source.coverage_end}</dd>
      <dt>Dimensions</dt><dd>{source.dimensions.join(", ")}</dd>
    </dl>}
    {session && <button className="secondary" disabled={busy} onClick={() => void onClear()}>
      Clear data and end session
    </button>}
    <p className="small">CSV rows stay in server memory. They are never uploaded to BigQuery or sent to an AI model.</p>
  </section>;
}
