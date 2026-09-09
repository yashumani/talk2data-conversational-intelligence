# Gemini API demo and activation

Gemini is a separate, optional language adapter for the CSV and signed internal runtimes.
The demonstration example selects `gemini-3-flash-preview` with explicit preview opt-in.
Claude remains available as a separately configured alternative. The rules-only CSV demo
continues to run without a model key. No model is enabled by installing the repository.

## Availability and cost

Google's [pricing page](https://ai.google.dev/gemini-api/docs/pricing) currently lists a free
standard API tier for `gemini-3-flash-preview`. That does not make every preview model free,
guarantee quota, or make requests free on a billing-enabled project. Check your AI Studio
project's actual tier and [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).
Preview availability, model versions and limits can change; re-run acceptance after a model
change. No paid fallback or automatic model substitution is implemented.

The free-tier pricing table says submitted content can be used to improve Google's products.
Use synthetic questions and definitions in this demo. CSV rows and query results stay in the
backend, but the question itself and permitted metric/dimension definitions are sent to Google.
Private enterprise use needs its own approved provider terms and data policy. BigQuery read
permission does not constitute permission to send business definitions to a model provider.

## Start the CSV workspace with Gemini

1. Obtain a key for the intended Gemini Developer API project through
   [Google AI Studio](https://aistudio.google.com/api-keys). Confirm the project's tier and quota.
2. Supply it as the local shell environment variable `GEMINI_API_KEY` using your secret manager
   or a hidden-input prompt. Do not place the value in source files, the browser, or this chat.
3. Start the optional language overlay from the repository root:

```bash
docker compose -f docker-compose.csv-demo.yml -f docker-compose.csv-gemini.yml \
  up --build --wait --wait-timeout 120
```

Open <http://127.0.0.1:8000/workspace/>. The header should read **Gemini assisted**. Start a
session, upload the supplied synthetic CSV, use the anchor **2026-08-01**, and ask:

> What were mobile activations by region last month?

The fixture's July regional values must sum to **24,676**. Inspect the definition citations,
returned rows, verification and Gemini usage. A failed or quota-limited request must produce
an error without a new answer. Reproducing an earlier successful answer reuses its saved
interpretation and original provider/model evidence with zero additional model calls.

The overlay mounts `examples/gemini/csv-preview.json` read-only and maps the key to
`T2D_GEMINI_API_KEY` inside the Python container. It enables no BigQuery, Cloud Run or Cloud SQL
resource. Avoid printing fully expanded Compose configuration when secrets are in the environment.
Using the base CSV Compose file alone starts the rules-only profile again.

For a local Python process, use the same isolated configuration:

```bash
python scripts/dependencies.py install dev
export T2D_CSV_DEMO_ENABLED=true
export T2D_OLLAMA_ENABLED=false
export T2D_OLLAMA_REQUIRED=false
export T2D_CSV_LANGUAGE_CONFIG_FILE="$PWD/examples/gemini/csv-preview.json"
# Supply T2D_GEMINI_API_KEY privately through your environment/secret manager.
uvicorn talk2data.main:app --host 127.0.0.1 --port 8000
```

For the React UI in this Python-only path, first build `apps/web` and set `T2D_WEB_DIRECTORY`
to its absolute `dist` directory as described in the activation guide. The Docker path packages
those assets automatically. GitHub Pages remains the public synthetic tour; a GitHub Actions
secret does not host a Python backend or activate Gemini in the Pages browser.

## Real API acceptance (LA-1 for the selected Gemini provider)

Add repository Actions secret **`GEMINI_API_KEY`**, then manually run **Gemini live acceptance**
on the reviewed candidate. The model input defaults to `gemini-3-flash-preview`. Normal PR checks
only report configuration status; they never run billable Gemini requests automatically.

The live benchmark shares the Claude acceptance cases and independent calculations: five
answer cases, three abstentions, and an instruction-injection rejection. It permits one
generation attempt per question, for at most eight generations plus token-count requests.
Each successful answer is replayed with the configured provider removed to verify zero new
calls. The artifact records selected provider, configured/observed model, fixture hash, case
results and token usage; it omits API keys, prompts, session capabilities and model reasoning.

Require the **live** job and all nine cases to pass. A green configuration job, a skipped
benchmark, recording transports or a quota failure cannot satisfy LA-1. Gemini evidence is
for Gemini; it does not validate Claude. Production evidence must still bind the actual source,
image and private configuration and pass the existing owner-review process.

## Architecture and boundaries

| Component | Responsibility |
| --- | --- |
| `core/language_config.py` | Shared egress, tenant/metric/classification scope and run limits |
| `core/gemini_config.py` | Gemini model, preview opt-in, private secret reference, data policy and thinking settings |
| `services/language_factory.py` | Explicit provider selection; rejects unknown providers and mismatched transports |
| `services/language_contract.py` | Shared approved-catalog filtering, strict proposal validation, grounding and replay |
| `services/gemini_transport.py` | Fixed Google endpoint, header authentication, timeouts and response-size bound |
| `services/gemini_interpreter.py` | Native Gemini request/response handling and usage accounting |
| Existing query tools | Policy, query compilation/execution, verification and evidence-based answer composition |

The adapter uses the existing locked `httpx` dependency and Google's native
[generateContent](https://ai.google.dev/api/generate-content) and
[countTokens](https://ai.google.dev/api/tokens) REST methods. It does not use Vertex AI or ADC.
The model receives one question and the permitted catalog, with a JSON schema limiting output
to metric ID, grouping IDs, intent and clarification state. It receives no tools, physical table
names, data rows, credentials or permission grants. Shared deterministic checks retain authority.

Input bytes and counted tokens are bounded before generation. Output usage includes both
visible candidate and thinking tokens; cached input is counted once as part of the prompt total.
Inconsistent usage, excess budgets, unexpected model IDs, multiple candidates, nonterminal
responses, tool/thought output, invalid JSON or unapproved IDs fail before a data query.
The sample allows one concurrent request and one model attempt per run. Raising the attempt
cap enables only bounded 429/503 retries; failed-attempt reservations remain charged when usage
is unknown. Neither a startup check nor a configured key asserts live provider readiness.

`thinking_level` uses Gemini 3's thinking-level control and defaults to `minimal` for the demo.
For a reviewed model that does not support this field, set it to `null` and validate the exact
model separately. This adapter does not disable provider safety checks or request thought text.

## Optional private runtime

Private configuration can enable a `gemini` block with `data_policy: "approved_enterprise"`,
approved tenants/metrics/classification, model and secret reference. Keep `claude.enabled`
false: enabling both providers is rejected. The demo's `synthetic_demo` policy is rejected
by internal configuration. Supply `T2D_GEMINI_API_KEY` to that private backend independently
of BigQuery ADC and independently of the CSV process.

The direct BigQuery and Parquet modes use this selection without Cloud Run or Cloud SQL.
The optional managed Terraform template still has its existing Claude secret binding; Gemini
on that profile needs a separately reviewed secret binding before deployment. This change
does not claim to activate or validate managed GCP, SSO, private data egress or enterprise readiness.
