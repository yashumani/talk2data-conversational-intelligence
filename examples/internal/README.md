# GCP / BigQuery connection placeholders

Connection status: **not configured**. Cycle 2 accepts these placeholders; live cloud
activation and validation are deferred to DG-1 in the product plan.

| Template | Fill in privately before activation |
| --- | --- |
| `runtime.example.json` | Approved billing project, BigQuery location, byte limits, IdP trust and private file paths |
| `catalog.example.json` | Approved views/dependencies and metric/dimension physical bindings |
| `entitlements.example.json` | Verified subjects and server-owned tenant, action, row and classification permissions |
| `domain.synthetic.yaml` | Business-owned metric and dimension definitions; supplied data is synthetic only |
| `live-acceptance.example.json` | Approved benchmark cases, exact results, signed token paths and inaccessible synthetic probe |

`example-project`, identity hosts, view names and users are fictional values. These files do
not connect GCP or grant permissions. The private API requires explicit configuration and ADC;
missing settings fail startup. Never supply internal configuration to the public demo process.

For working data now, use the separate optional CSV import in the React workspace, following
`docs/CSV_WORKSPACE.md`. CSV data stays in its isolated workspace and is never loaded into
BigQuery. Configure each connection separately when its environment is available.

The optional `governance_database_path` and `state_database_path` are null in the placeholder.
A private deployment must supply an absolute state path and a service-owned writable volume
to retain conversations/results/events across restarts. Definitions use the explicit governance
path, otherwise the state path. Both unset means memory only. Keep one worker per local file;
see `docs/DURABLE_CONVERSATIONS.md` and `docs/DEFINITION_GOVERNANCE.md`. CSV persistence uses
its own separate configuration and is unaffected by these private store settings.
