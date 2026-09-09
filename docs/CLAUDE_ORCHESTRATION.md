# Cycle 4: Claude interpretation and bounded specialists

Updated: 2026-09-08. Implementation and local contract tests are provided in this increment.
**LA-1, real Claude acceptance, remains open until the opt-in benchmark passes against an
approved model.** Configuration, mock HTTP tests and coverage cannot close that gate.
GCP/SSO remains separately deferred under the user's accepted DG-1 boundary.

## Product behavior

The optional React CSV workspace and separate internal Python API now run a bounded sequence:
resolve meaning, compile a business query, execute the selected connection, verify the result,
and compose a certified answer. Claude can assist only the first step. The other specialists
reuse the existing deterministic services. This is one language-model interpreter with five
registered specialist roles; it does not make five independent model calls.

CSV defaults to rules-only and requires no model account. When explicitly enabled, the UI
labels Claude interpretation and explains that questions and approved definitions are sent to
Claude. CSV rows, query results, access grants and physical source mappings are not serialized
into provider requests. Free-text questions themselves may contain information entered by a
user: this implementation is not a DLP scrubber. Enable egress only for an approved audience.

BigQuery remains an internal, separately configured connection. Enabling Claude changes
interpretation, not connection selection. A failed model request does not retry through Ollama,
the rules interpreter or another data connector. Disabling Claude in server configuration is
an explicit rules-only mode, displayed to the user.

## Code and dependency boundaries

| Module | Responsibility |
| --- | --- |
| `core/claude_config.py` | Validated provider opt-in, private secret reference, egress allowlists and budgets |
| `services/claude_transport.py` | Fixed Anthropic HTTPS endpoint, authentication, bounded response parsing and sanitized errors |
| `services/claude_interpreter.py` | Authorized definition projection, schema request, provider validation and deterministic grounding |
| `services/agent_runtime.py` | Registered stage order, execution deadline, model/token reservations and cancellation |
| `domain/agents.py` | Typed stage and usage reports; no model reasoning |
| `services/demo_chat.py` | Compose existing admissibility/compiler/query/verification/composition tools |
| `services/csv_workspace.py` | Isolated session/source/definition binding and saved interpretation replay |
| `internal/runtime.py` | Trusted internal identity and BigQuery binding, per-request specialist run |
| `api/agent_errors.py` | Sanitized status/code/report response with `Cache-Control: no-store` |
| `apps/web/src/components/AgentRunPanel.tsx` | Show completed processing stages, provider and usage |

Python 3.11+ implements the API and orchestration; React with TypeScript implements the UI.
HTTPX, already a backend dependency, implements the two required provider operations.
No separate agent framework, shell tool, arbitrary MCP server or cloud SDK is added to the
language adapter. Main files retain application composition rather than provider logic.

## One request, in detail

1. The server binds identity, selected source and current approved definition snapshot.
   Internal callers cannot supply their own roles or data scope. CSV owns a separate,
   ephemeral demo identity and connector registry.
2. `AgentRun` starts a deadline and empty usage ledger. Each registered stage may run once,
   in order. No model output chooses a stage or a Python callable.
3. Before egress, filter the catalog by tenant, permitted ask/read actions, classification,
   approved metric IDs, available source metadata and visible dimensions. A question naming
   a recognized but excluded metric/dimension is denied before contacting Claude.
4. Project only IDs, names, descriptions, aliases, definition versions and allowed dimensions.
   The current approved publication is resolved again for each new question; no persistent
   prompt cache can retain an old definition in this adapter.
5. Apply the request byte cap; count the exact model/system/messages/schema input through
   `messages/count_tokens`; reject excessive estimated tokens; reserve input plus the maximum
   output allowance before a Messages request.
6. Claude returns a strict proposal: one nullable `metric_id`, `dimensions`, `intent`, and
   `needs_clarification`. Extra properties, SQL, tool calls, arbitrary text responses, unknown
   IDs, duplicate dimensions, invalid usage and incomplete output are rejected.
7. Resolve enum casing against approved IDs. Explicit metric names cannot be replaced by a
   conflicting proposal. Requested grouping must match named dimensions. Rules retain date,
   calendar, filter and operation parsing; Claude cannot inject filters or query expressions.
8. The query planner validates the approved metric, aggregation, dimensions and access context
   and compiles Business Query IR. The existing selected connector executes it under its
   own limits. Verification checks bounds, coverage, result consistency and lineage.
9. Only verified results reach the deterministic answer composer. Attach the definition
   citations and stage report. Recheck the pinned definition for revocation before release.

The raw Messages request uses `output_config.format.type = "json_schema"`, a manually bounded
schema and `anthropic-version: 2023-06-01`. Pydantic independently validates the response.
Refusal and output-token exhaustion can arrive with HTTP 200 and must still fail closed.
The implementation follows Anthropic's [structured output contract](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
and [token counting contract](https://platform.claude.com/docs/en/api/messages/count_tokens).

## Registered roles and limits

| Role | Sole registered tool | Authority |
| --- | --- | --- |
| Semantic resolver | `interpret_governed_question` | Propose approved business meaning or clarification |
| Query planner | `compile_business_query` | Compile and authorize the existing typed query contract |
| Query executor | `execute_bound_query` | Execute only the server-selected connector |
| Result verifier | `verify_query_receipt` | Withhold results that fail evidence checks |
| Answer composer | `compose_certified_answer` | Format only validated numerical claims |

The coordinator has no model-controlled branching or recursion. Clarification, denied access,
missing source, invalid planning or failed verification terminates before later stages.
The optional context-research role remains unconnected; unsupported causal/contextual requests
continue to abstain. The existing Hermes integration remains an extension boundary.

| Budget | Default | Configuration range / meaning |
| --- | --- | --- |
| Total request deadline | 90 seconds | 1–180 seconds |
| Stage executions | 6 maximum | 1–6; only five registered roles exist, each once |
| Messages attempts | 1 | 1–2; includes failed attempts, excludes token-count preflight |
| Input tokens | 8,000 | 128–16,000; preflight and observed usage checked |
| Output tokens | 512 | 128–2,048; sent as provider `max_tokens` |
| Total reserved tokens | 12,000 | 512–40,000 across attempts |
| Serialized request bytes | 40,000 | 512–80,000 before any provider call |
| Provider operation timeout | 25 seconds | 1–60, also bounded by remaining run time |
| Concurrent language requests | 4 | 1–8 per runtime process |
| Provider response | 65,536 bytes | Fixed streaming-body cap |
| Claude questions per CSV session | 8 | `T2D_CSV_DEMO_MAXIMUM_LANGUAGE_QUESTIONS`, 1–20; failures consume quota |

With a two-attempt budget, only HTTP 429 or 529 can trigger one retry. Delay is one second
unless a valid numeric `Retry-After` supplies 0–5 seconds within the remaining deadline.
Connection failures, timeouts, authentication errors and malformed output do not trigger retries.
Redirects and environment proxy discovery are disabled; the fixed destination is
`https://api.anthropic.com/v1/`. An approved hosted endpoint needs a separate adapter and review.
See the provider's [API error reference](https://platform.claude.com/docs/en/api/errors).

Reservations are conservative application limits, not a guaranteed provider billing cap.
Token counts are estimates; observed usage is known only after a response. A failed request
can have unknown billable usage, so its reservation remains charged and `usage_complete`
stays false after a retry. Per-process/per-session bounds do not replace account spending
limits, authenticated ingress or distributed quotas in Cycle 6.

## Configure CSV interpretation independently

1. Copy `examples/claude/runtime.example.json` to an absolute private path outside the repo.
2. Select an approved model supporting the documented structured-output contract. There is
   no default model. Set `enabled` and `egress_approved` to true only after approval.
3. For the packaged synthetic demo, allow only tenant `demo-telecom` and metric
   `MOBILE_ACTIVATIONS`, with `maximum_classification: "INTERNAL"`.
4. Inject the API key as `T2D_CLAUDE_API_KEY` through the runtime's secret mechanism. Keep
   `secret_ref: "env://T2D_CLAUDE_API_KEY"`; never place a literal key in JSON or frontend config.
5. Set `T2D_CSV_LANGUAGE_CONFIG_FILE` to that absolute path, enable CSV as documented in the
   [CSV runbook](CSV_WORKSPACE.md), and restart the single-worker API.

The packaged Compose profile stays rules-only; an operator must explicitly mount the private
JSON and inject these environment variables to enable Claude in a container. Startup rejects
an incomplete enabled configuration or an unresolved secret. The state endpoint reports
`CONFIGURED_NOT_LIVE_VERIFIED` when configured: startup alone does not perform a paid probe or
prove provider health. Successful answers separately record the resolved provider model.

## Configure the separate internal application

The private `InternalRuntimeConfig` accepts an optional `claude` object with the same schema.
Use approved internal tenant/metric IDs and the authorized egress classification ceiling.
The internal app does not read `T2D_CSV_LANGUAGE_CONFIG_FILE`; the CSV app does not read the
internal configuration. BigQuery configuration, credentials and source mappings remain under
the existing private runtime boundary. `GET /v1/internal/language` requires verified identity
and reports configuration state without exposing the key, allowlists or private model config.

Internal provider failure releases neither a data query nor an old answer. Existing internal
cancellation propagates through the in-flight interpreter and connector operations. Actual
GCP cancellation, cloud IAM and SSO acceptance remain DG-1; mock contracts cannot prove them.

## Saved answers and frontend synchronization

A successful CSV run retains the validated interpretation along with the original question,
`as_of`, source bytes, definition snapshot and actual model name. Reproduction performs the
deterministic stages again against those retained inputs, checks revocation and marks
`replayed_interpretation: true` with zero new model calls. It does not silently select the
saved upload as the current data source. Only successful, verified runs enter history.

The UI clears the prior answer when a new question begins and shows provider failure explicitly.
The processing panel shows role, status and usage, not chain-of-thought. These are response
reports; progress streaming, durable events, reconnect, cross-device state and restart recovery
remain Cycle 5. CSV history remains four runs in an ephemeral session.

## Verification and live gate LA-1

Contract tests use synthetic HTTP responses to prove payload isolation, current definitions,
grounded IDs, error/usage handling, deadlines, cancellation, fixed tool order and saved replay.
Internal tests use signed test identities and recording BigQuery transports. They are not
real provider, SSO or cloud acceptance. Coverage floors remain 96% independently for Python
lines/branches and React lines/statements/functions/branches with all production modules included.

`tests/test_live_claude.py` makes real HTTPS calls without a mocked provider. Five positive cases
cover exact regional/channel/total sums, a paraphrase and the previous complete day; expected
numbers are calculated independently from the public CSV. Three negative cases must abstain
(unsupported revenue, ambiguity and an unrelated request); provider failure does not count as
abstention. A ninth injection case must fail before a model call. Each positive answer must
reproduce without the transport. All nine cases must pass. At most eight Messages calls are
made, each with a single attempt and the configured input/output caps.

This is a small regression acceptance set, not a statistical claim of 95% language accuracy.
Production still needs business-owned questions, broader metric/calendar/ratio scope and
ongoing evaluations. A successful artifact records model, case status, usage and fixture hash.

For GitHub Actions, configure these repository settings:

| Setting | Purpose |
| --- | --- |
| Secret `ANTHROPIC_API_KEY` | Approved provider account, injected only into the job environment |
| Variable `T2D_CLAUDE_MODEL` | Approved structured-output model ID; manual dispatch may supply it |
| Variable `T2D_CLAUDE_ACCEPTANCE_APPROVED=true` | Approve the bounded public synthetic benchmark egress and cost |

The `Claude live acceptance` workflow runs on relevant same-repository PRs when all settings
exist, or by manual dispatch once available on the default branch. Fork PRs cannot use it.
Without configuration it records `NOT_CONFIGURED` and skips the live job. A green configuration
job or skipped live job does not close LA-1. Retain the passing live artifact and exact source
commit on the PR before declaring Cycle 4 accepted.

To run locally with the private configuration and injected key:

```bash
T2D_RUN_LIVE_CLAUDE=1 \
T2D_CLAUDE_ACCEPTANCE_CONFIG=/absolute/private/claude-acceptance.json \
T2D_CLAUDE_ACCEPTANCE_REPORT=/absolute/private/claude-acceptance-report.json \
python -m pytest tests/test_live_claude.py -q
```

No GCP connection is needed for this gate. LA-1 is pending configuration, not user-deferred.
Cycle 5 begins after the current milestone's acceptance boundary is resolved.
