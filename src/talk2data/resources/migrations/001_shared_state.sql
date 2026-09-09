CREATE TABLE t2d_schema (version integer PRIMARY KEY CHECK (version = 1));
INSERT INTO t2d_schema VALUES (1);
CREATE TABLE t2d_admission (id integer PRIMARY KEY CHECK (id = 1));
INSERT INTO t2d_admission VALUES (1);
CREATE TABLE t2d_conversations (
    id uuid PRIMARY KEY, owner text NOT NULL, scope text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(), payload text NOT NULL
);
CREATE INDEX t2d_conversations_owner ON t2d_conversations(owner, scope);
CREATE TABLE t2d_runs (
    id uuid PRIMARY KEY,
    conversation uuid NOT NULL REFERENCES t2d_conversations(id) ON DELETE CASCADE,
    request_id uuid NOT NULL, request_hash text NOT NULL, status text NOT NULL
      CHECK (status IN ('QUEUED','RUNNING','CANCELLATION_REQUESTED','COMPLETED','FAILED','CANCELLED','INTERRUPTED')),
    payload text NOT NULL, grant_payload text NOT NULL, tenant text NOT NULL, binding text NOT NULL,
    expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    fence uuid, lease_until timestamptz,
    UNIQUE(conversation, request_id)
);
CREATE UNIQUE INDEX t2d_one_active_run ON t2d_runs(conversation)
    WHERE status IN ('QUEUED','RUNNING','CANCELLATION_REQUESTED');
CREATE INDEX t2d_queue ON t2d_runs(status, binding, created_at);
CREATE TABLE t2d_events (
    run_id uuid NOT NULL REFERENCES t2d_runs(id) ON DELETE CASCADE,
    sequence integer NOT NULL, payload text NOT NULL, PRIMARY KEY(run_id, sequence)
);
CREATE TABLE t2d_definitions (namespace text PRIMARY KEY, revision integer NOT NULL, payload text NOT NULL);
CREATE TABLE t2d_grants (issuer text PRIMARY KEY, revision integer NOT NULL, payload text NOT NULL);
CREATE TABLE t2d_grant_audit (
    issuer text NOT NULL, revision integer NOT NULL, digest text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(issuer, revision)
);
