# Optional managed scale-out bundle

This Terraform root is optional. It provisions Cloud Run, IAP, private networking and Cloud SQL
for a multi-replica API/worker deployment. It is not needed for either direct BigQuery with local
SQLite state or BigQuery-to-Parquet operation.

Do not apply this root merely to authorize BigQuery. Use an existing read-only workload/user
principal and the private runtime configuration described in `docs/BIGQUERY_PARQUET_RUNTIME.md`.

When this bundle is selected, it deliberately requires the shared PostgreSQL configuration and
the separate database bootstrap procedure. `minimum_instance_count` defaults to zero so Cloud Run
can scale down when idle; set it above zero only for an approved latency/SLA requirement. Cloud SQL
still incurs cost while provisioned and should be created only for the managed scale-out profile.
