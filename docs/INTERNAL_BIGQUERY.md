# Cycle 2: trusted identity and internal BigQuery

Status: **Cycle 2 complete on the user-approved placeholder boundary.** Live GCP/SSO activation
and acceptance are deferred to release gate DG-1; they have not passed. The
accepted Cycle 1 baseline is `ba198541dc14821dc497217e97cf67db20234d5c` (PRs #18 and #19).
This increment implements requirements R1, R4 and the identity portion of R9 in the
[product plan](PRODUCT_ORCHESTRATION_PLAN.md). It preserves the independent CSV demonstration.

## What the implementation does

The private Python API verifies signed identity tokens, resolves server-owned permissions,
loads approved semantic and physical contracts, compiles a parameterized SELECT, checks a
BigQuery dry run, executes a bounded job and validates the evidence before releasing an answer.
The existing deterministic interpreter, semantic registry, compiler, typed query tool,
verification and answer services are reused. No model is called in this increment.

| Module | Responsibility |
| --- | --- |
| `internal_main.py` | Thin private ASGI entry point |
| `internal/bootstrap.py` | Private configuration, identity middleware, tenant registries and lifecycle |
| `internal/routes.py` | Strict HTTP schemas, access checks, cancellation ownership, final permission recheck |
| `internal/runtime.py` | Bounded in-process requests and use of the governed question pipeline |
| `core/internal_config.py` | Required private paths and pinned identity trust configuration |
| `services/identity.py` | JWT signature/claims verification and private entitlement lookup |
| `core/bigquery_config.py` | Separate cloud project, location and query limits |
| `domain/bigquery_mapping.py` | Exact view/column bindings and agreement with approved business definitions |
| `services/bigquery_sql.py` | Single parameterized SELECT with mandatory scope predicates |
| `services/bigquery_port.py` | Testable SDK-independent execution boundary |
| `services/bigquery_sdk.py` | Official Google client, ADC, metadata, job polling and cancellation |
| `connectors/bigquery.py` | Authorization, dry-run controls, result validation and receipts |

The public `main.py` does not import or initialize the BigQuery SDK. Its container installs
the base package; the private container installs the `internal` extra. The private API mounts
no CSV, legacy demo, connector-configuration, documentation or React asset endpoints.
The existing React workspace remains the CSV demo. An authenticated internal React experience
will consume the durable run protocol in Cycle 5; this increment supplies its trusted API boundary.

## Identity and authorization

Each deployment pins one HTTPS issuer, exact audience, HTTPS JWKS endpoint, signature algorithm
and token header. Bearer mode supports RS256 or ES256. Signed IAP mode requires ES256,
`https://cloud.google.com/iap`, Google's fixed JWK endpoint and a maximum token lifetime of
600 seconds plus twice the configured clock skew. Unsigned user-email headers never authenticate
a request. See Google's [signed IAP header contract](https://docs.cloud.google.com/iap/docs/signed-headers-howto).

The verifier requires `iss`, `aud`, `sub`, integer `iat` and integer `exp`, and checks signature,
expiry, issue time and bounded lifetime. It rejects duplicate token headers, unsupported
algorithms, caller-selected key URLs, oversized tokens and missing key IDs. JWKS caching is
bounded; individual signing keys are not cached indefinitely. These controls use
[PyJWT's verification API](https://pyjwt.readthedocs.io/en/stable/api.html).

The verified subject is looked up in a private entitlement file. Roles, tenant, regions,
business units and classification in the caller's JWT or request body cannot grant access.
One subject has one explicit tenant binding in this increment. Multiple independent tenants
can be configured in one process, but one subject cannot select between tenants.

Publish entitlement updates atomically in a read-only mounted directory. Grants are re-read
for every authenticated request and again after a query, before releasing its result. Removed
grants or changed permissions block that release. A broken/missing grants file or unavailable
key service produces a failure, never demo access. This is revocation at verification boundaries;
it is not an instantaneous distributed revocation event system.

Question execution requires explicit `ASK_BUSINESS_QUESTIONS` and `READ_AGGREGATED_DATA` grants,
nonempty region and business-unit scope, and adequate metric/dimension classification.
Classification also applies inside the connector to direct typed-tool calls, including dimensions
used only as filters. Cancellation looks up the combination of tenant, subject and request ID.

This service verifies tokens issued by the approved SSO/ingress. It does not provision an
identity provider, implement a browser login flow or configure private ingress. Configure
TLS, request-size/rate limits and deployment authentication at the approved ingress before use.

## Approved BigQuery contract

Physical mappings are private data-owner contracts, not user inputs. Each tenant/connector
binding specifies an exact `project.dataset.view`, its approved dependency references and
version, plus semantic metric and dimension IDs. Identifiers are validated separately from
bound values; wildcard references, arbitrary expressions and raw SQL are not accepted.

The source is an approved logical or materialized view in the configured location. Its
canonical daily-fact shape is:

| Logical field | BigQuery shape and meaning |
| --- | --- |
| Tenant, business unit, metric selector | Distinct STRING columns with server-approved values |
| Region and other mapped dimensions | Distinct STRING columns bound to governed semantic IDs |
| Fact date | DATE containing the business observation day |
| Source update time | TIMESTAMP maintained by the source owner |
| Additive measure | Numeric column for an approved SUM metric |
| Ratio measures | Governed numeric numerator and denominator; calculated as SUM(numerator) / SUM(denominator) |

Startup checks view type, location and required column types. Every available metric in a
private domain pack must have an exact mapping. Semantic version, aggregation, value type,
unit, currency, dimensions, classifications and supported time grains must agree. Domain
packs must be approved, currently effective, Gregorian and UTC. Duplicate bindings, case-insensitive
column collisions and use of scope columns as measures are rejected before a cloud client is created.

This increment supports daily observations aggregated over a requested period, including a
comparison in the same job. It rejects hourly requests, unsupported semantic grains, fiscal
calendars, non-UTC calendars and windows longer than 731 days. It does not reinterpret existing
corporate fiscal definitions as Gregorian. Data owners must approve a compatible view/definition
or the required calendar implementation must be completed before that metric is enabled.

SUM and RATIO are the physical mapping operations implemented here. Other aggregates,
arbitrary joins and automatic schema adaptation remain unavailable. Ratios use governed
numerators and denominators rather than averaging displayed percentages. Values flow through
the existing floating-point answer contract; integer results outside the exact JavaScript-safe
range are rejected. Accounting-grade decimal serialization requires an explicit later contract.

## Execution controls and evidence

1. Verify identity and definition access, then compile an approved logical plan.
2. Validate that plan again at the connector, including tenant, actions, region/unit scope,
   classification, dimensions, filters, metric contract, dates and row cap.
3. Bind tenant, region, business unit, metric selector, filters, dates and row limit as parameters.
   Mandatory scope predicates remain present even for a total with no grouping.
4. Dry-run the exact statement. Require SELECT, the configured location, known nonnegative
   scanned bytes within budget and nonempty referenced objects contained in the private allowlist.
5. Submit the same statement with an explicit job ID, `maximum_bytes_billed`, server job timeout,
   bounded client waits and result-page limit. Query cache and failed-job resubmission are disabled.
6. Reject incomplete jobs, mismatched job identity/location/project, truncated results, duplicate
   groups, non-finite/undefined measures, invalid update timestamps and incomplete daily groups.
7. Reuse semantic result verification, then re-verify identity/permissions before HTTP release.

Current/comparison periods execute in one job. Each returned group must contain every requested
day, including explicit observations for known zero days. This establishes structural coverage;
it does not prove every business event or expected region/store was loaded. The data owner must
certify the approved view's business completeness. Equal-length prior-period comparison follows
the existing shared contract; it is not always the previous calendar month.

Default application limits are 100 result groups, a 60-second job wait, 10-second SDK calls
and eight concurrent in-process questions. Maximum bytes billed is required private configuration.
A stricter connector row limit is honored by the shared question service. Parameterized LIMIT
does not constrain scanned bytes. BigQuery job timeout and cancellation are best effort; a
cancellation request does not prove the warehouse stopped or that no charges were incurred.
See [QueryJobConfig](https://docs.cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.job.QueryJobConfig)
and [QueryJob](https://docs.cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.job.QueryJob).

Receipts add cloud job ID, billing project/location, estimated/processed/billed bytes where
reported, cache state, timestamps, scope hash and semantic version. Existing mapping/SQL/result
hashes and resolved/comparison periods remain available. `source_snapshot` is the maximum
source-owned update timestamp observed; it is not a BigQuery time-travel snapshot or a durable
copy of the source. Reproducible historical reruns require future source-retention controls.

Stable cloud job IDs identify a compiled query and authorization scope. A repeated HTTP request
after completion is not idempotent in this increment and may create another job. Durable request
deduplication, run recovery, event streaming, audit retention and conversation history belong to
Cycle 5 and Cycle 6. Run one worker/instance during this acceptance phase so request ownership,
capacity and cancellation share the same in-memory registry.

## Private configuration and runtime

The five files in `examples/internal/` are synthetic shapes only. `example-project`, the identity
host, view, users and expected results are fictional. They do not connect to a real project or
certify any company definition. Copy and adapt them in the approved private location:

| Private file | Content |
| --- | --- |
| `runtime.json` | Identity trust, billing project/location, query limits and absolute private paths |
| `entitlements.json` | Issuer and subject-to-tenant/action/scope/classification bindings |
| `catalog.json` | Approved views, dependencies, columns and semantic contracts |
| `domains/*.yaml` | Approved business definitions; immutable for this process lifetime |
| `acceptance.json` | Approved benchmark questions, exact expected rows, token-file locations and forbidden synthetic probe |

The runtime reads `T2D_INTERNAL_CONFIG_FILE`. There are no fallback project IDs or default
internal grants. Definitions and physical mappings are pinned at startup; update them through
an approved restart until atomic semantic publication is implemented in Cycle 3. Keep all real
files outside this public repository and the Docker build context.

BigQuery uses Application Default Credentials. In GCP, attach the approved workload identity
to the private service; do not download service-account keys. Give it only the required query
job permissions in the approved billing project and metadata/read access to approved views.
The platform owner must review inherited roles, view authorization, policy tags and any row
policies. [Authorized views](https://docs.cloud.google.com/bigquery/docs/authorized-views) can expose
approved subsets without granting direct access to source datasets; consult Google's
[BigQuery access controls](https://docs.cloud.google.com/bigquery/docs/access-control) for the exact grant scope.

All requests in a deployment currently use its workload principal. Application subject/region
predicates are not delegated end-user BigQuery identities. Warehouse-enforced restrictions must
be configured for that workload, and stronger tenant isolation may require separate deployments
and principals. A dry run and the application's read-only compiler do not replace IAM.

For an approved local acceptance environment, `docker-compose.internal.yml` is a standalone
loopback-only profile. It requires `T2D_PRIVATE_CONFIG_DIRECTORY` and
`T2D_ADC_CONFIGURATION_FILE`, a read-only approved federated ADC configuration. Ensure UID 10001
can read the mounts and that any federation credential-source path resolves inside the container.
The Compose profile does not create identity federation or grant cloud permissions.

```bash
docker compose -f docker-compose.internal.yml up --build --wait --wait-timeout 120
```

The private API listens on local port 8001. `GET /health/live` is unauthenticated liveness;
`GET /health/ready` requires a valid identity and reports completion of startup validation,
not continuous warehouse availability. Production Cloud Run deployment should use metadata
ADC and approved configuration mounts rather than the local Compose identity-file mount.

## API

| Request | Behavior |
| --- | --- |
| `GET /v1/internal/me` | Server-resolved tenant, subject and row scope |
| `GET /v1/internal/metrics` | Metric definitions visible to the subject's classification/action grants |
| `POST /v1/internal/chat` | Strict question, optional UUID request ID and aware `as_of`; returns governed answer or abstention |
| `POST /v1/internal/queries/{request_id}/cancel` | Owner-only cancellation request; 202 requested, 404 absent/other owner |

Chat bodies do not accept roles, access contexts, tenant, connector, project, SQL or model
switches. Signed identity belongs in the configured request header, never the JSON payload.
422 diagnostics omit raw submitted values. Missing/rejected identity returns 401; insufficient
access or changed grants return 403; occupied/duplicate active requests or cancelled answers
return 409; query deadlines return 504; unavailable identity verification returns 503.

## Acceptance and remaining gate

The ordinary suite exercises real RSA/EC signature verification with test keys, strict API
contracts and a recording cloud port. SDK tests inspect real Google SDK configuration objects
while replacing network calls. Those tests do not prove live IAM, warehouse behavior or SSO.

The `Internal runtime package` workflow builds the separate image and checks installed imports,
the non-root user, absence of bundled UI and failure without private configuration. The existing
CSV container/HTTP, React, PostgreSQL, Ollama, Python matrix and CodeQL gates remain active.

Run the real cloud tests only against the approved isolated acceptance environment:

```bash
T2D_RUN_LIVE_BIGQUERY=1 \
T2D_BIGQUERY_ACCEPTANCE_FILE=/approved/private/acceptance.json \
python -m pytest -m live_bigquery -q --tb=short
```

The manifest requires at least two independently authorized scopes, fresh signed tokens,
business-owned questions with exact expected rows and an owner-approved inaccessible synthetic
probe view. The tests use the real JWKS service, ADC and Google SDK. They check signed identity,
caller-authority rejection, scoped numeric results with receipts, a Forbidden response for
the probe and abstention under a one-byte scan budget. Supply an uncached fixture whose dry-run
estimate exceeds one byte. Preserve logs/reports privately because failures may include
approved benchmark metadata.

Before enabling a real internal connection, these real checks must pass and the platform owner must record private ingress,
restricted runtime IAM, supported source schema, dependency allowlist and a controlled live
cancellation/timeout observation. Do not test write denial by executing a write against business
data. No production GCP project, views, IdP, runtime identity or private configuration location
has yet been supplied or verified in this project. The user's subsequent direction explicitly
accepts connection placeholders and CSV as the working optional data source, closing Cycle 2
without activating GCP. Track the real checks as DG-1 in the product plan; enterprise release
still requires them. Continue Cycle 3 without requiring cloud credentials.
