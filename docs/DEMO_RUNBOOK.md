# Talk2Data demonstration runbook

This demonstration exercises a real local Ollama model while keeping all numerical answers deterministic and receipt-backed. The Unified AI Brain, Graphiti, Obsidian, external research, and anomaly services are intentionally not connected in this slice.

## Demonstrated path

```text
question
→ Ollama structured interpretation
→ deterministic Domain Pack validation
→ authorization and classification checks
→ Business Query IR
→ parameterized read-only SQLite execution
→ freshness and result-sense validation
→ certified claims and answer receipt
```

Ollama interprets the user's language. It does not calculate metrics, write SQL, authorize access, or invent numeric answers.

## Start the complete local demo

The Compose stack starts Ollama, pulls the configured model, starts Talk2Data, and seeds a synthetic telecom snapshot.

```bash
docker compose up --build
```

The default model is `qwen3:8b`. A smaller model can be selected on a lower-memory demonstration machine:

```bash
T2D_OLLAMA_MODEL=qwen3:1.7b docker compose up --build
```

Open:

```text
http://localhost:8000/demo
```

The API requires Ollama in the Compose demonstration profile. It will not silently fall back to rules if the model is unavailable.

## Automated smoke test

With the stack running:

```bash
python scripts/demo_smoke.py
```

The script verifies:

- Ollama readiness
- real `OLLAMA_AND_RULES` interpretation
- verified grouped churn results
- verified period comparison
- stale-current-period abstention
- valid-but-unconnected source handling
- out-of-domain rejection
- result receipt and hash presence

For backend-only development where Ollama is intentionally disabled:

```bash
python scripts/demo_smoke.py --allow-rules-fallback
```

## Recommended questions

1. `What was postpaid churn by plan last month?`
2. `Compare mobile activations in Northeast last month to the previous period.`
3. `What were mobile activations this month?`
4. `What was ARPA last month?`
5. `What is our restaurant food-cost margin by location?`
6. `Did food-delivery application traffic contribute to network congestion?`

These demonstrate verified answers, comparison logic, freshness abstention, a valid source gap, domain rejection, and the explicit AI Brain/context boundary.

## Synthetic data boundary

The connector uses synthetic telecom facts from July 2025 through July 2026. Its certified coverage ends on 2026-07-31 and its source snapshot is 2026-08-01T06:00:00Z. The fixed `as_of` date used by the UI is 2026-08-17 so demo outcomes remain reproducible.

## Live-model CI

The `Live Ollama demo smoke` GitHub workflow installs Ollama on a hosted runner, pulls `qwen3:0.6b`, and runs the marked end-to-end test against an actual model. Normal CI remains deterministic and does not download a model.

## Demonstration limitations

- No company or customer data is included.
- No Unified AI Brain context is used.
- External driver questions abstain rather than fabricate an explanation.
- Hermes multi-agent investigation is not activated in this slice.
- The SQLite adapter is a synthetic reference connector; production sources will implement the same governed execution boundary.
