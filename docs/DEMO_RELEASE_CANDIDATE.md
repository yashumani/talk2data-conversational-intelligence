# Talk2Data Demonstration Release Candidate

This branch is the demonstration release candidate for the Talk2Data conversational experience.

Included demonstration path:

1. Local Ollama interprets a natural-language telecom question into governed identifiers.
2. The Question Admissibility Engine validates business relevance, analytical validity, role permissions, and source readiness.
3. The deterministic compiler emits a Business Query IR.
4. A parameterized, read-only SQLite reference connector executes against synthetic telecom data.
5. The result-sense engine validates coverage, lineage, value type, metric bounds, row integrity, finiteness, and result hashing.
6. The response layer releases receipt-backed certified claims or abstains.
7. The browser experience at `/demo` exposes the answer, interpretation mode, decision, query plan, and receipt.

The Unified AI Brain context service is intentionally excluded from this release candidate and will be integrated as a separate governed dependency.

No production data, credentials, proprietary schemas, or private source identifiers are included.
