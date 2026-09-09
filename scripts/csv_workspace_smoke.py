"""Exercise the installed CSV workspace over HTTP using synthetic data only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API = "/v1/demo/csv"


def run(base_url: str) -> dict[str, Any]:
    checks: list[str] = []

    def check(condition: bool, label: str) -> None:
        if not condition:
            raise RuntimeError(f"CSV release acceptance failed: {label}")
        checks.append(label)

    def request(
        path: str,
        *,
        token: str | None = None,
        body: bytes | dict[str, Any] | None = None,
        expected: int = 200,
    ) -> bytes:
        headers = {} if token is None else {"X-Demo-Session": token}
        if isinstance(body, dict):
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        else:
            data = body
            if body is not None:
                headers["Content-Type"] = "text/csv"
        req = Request(base_url.rstrip("/") + path, data=data, headers=headers)
        try:
            with urlopen(req, timeout=20) as response:
                status, raw = response.status, response.read()
        except HTTPError as exc:
            status, raw = exc.code, exc.read()
        if status != expected:
            raise RuntimeError(f"{path}: expected HTTP {expected}, received {status}")
        return raw

    readiness = json.loads(request("/health/ready"))
    check(readiness.get("status") == "ready", "Application readiness is ready")
    html = request("/workspace/").decode()
    assets = re.findall(r'(?:src|href)="(/workspace/assets/[^\"]+)"', html)
    check(any(path.endswith(".js") for path in assets), "Built JavaScript is present")
    check(any(path.endswith(".css") for path in assets), "Built stylesheet is present")
    for path in assets:
        check(bool(request(path)), "Packaged asset is served: " + path)

    raw_csv = request("/workspace/samples/mobile-activations.csv")
    rows = list(csv.DictReader(io.StringIO(raw_csv.decode())))
    expected_totals: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        if row["date"].startswith("2026-07-"):
            expected_totals[row["region"]] += int(row["activations"])
    check(len(rows) == 736 and sum(expected_totals.values()) == 24676, "Synthetic fixture is complete")

    token = json.loads(request(API + "/sessions", body=b"", expected=201))["session_token"]
    other = json.loads(request(API + "/sessions", body=b"", expected=201))["session_token"]
    try:
        initial = json.loads(request(API + "/state", token=token))
        check(initial["source"] is None and initial["last_response"] is None, "Session starts empty")
        check(initial["internal_connections_available"] is False, "Internal connections are unavailable")
        source = json.loads(request(API + "/upload", token=token, body=raw_csv))
        fingerprint = hashlib.sha256(raw_csv).hexdigest()
        check(source["source_fingerprint"] == fingerprint, "Source fingerprint matches uploaded bytes")
        question = {
            "question": "What were mobile activations by region last month?",
            "as_of": "2026-08-01T12:00:00Z",
            "source_fingerprint": fingerprint,
        }
        answer = json.loads(request(API + "/chat", token=token, body=question))
        check(answer["status"] == "ANSWERED", "Supported question is answered")
        check(answer["verification"]["status"] == "VERIFIED", "Answer evidence is verified")
        receipt = answer["receipt"]
        actual_totals = {row["REGION"]: row["value"] for row in receipt["result_rows"]}
        check(actual_totals == dict(expected_totals), "Regional totals reproduce the CSV exactly")
        check(receipt["source_kind"] == "csv_demo", "Receipt identifies the CSV connector")
        check(receipt["source_fingerprint"] == fingerprint, "Receipt is bound to the selected source")
        check(answer["ai_model"] is None, "CSV answers require no model service")
        trace = answer["agent_run"]
        check(
            [step["role"] for step in trace["steps"]]
            == [
                "SEMANTIC_RESOLVER",
                "QUERY_PLANNER",
                "QUERY_EXECUTOR",
                "RESULT_VERIFIER",
                "ANSWER_COMPOSER",
            ]
            and all(step["status"] == "SUCCEEDED" for step in trace["steps"]),
            "Five specialist stages complete in the required order",
        )
        check(
            trace["provider"] == "rules" and trace["usage"]["model_calls"] == 0,
            "Default CSV processing does not call a language provider",
        )
        restored = json.loads(request(API + "/state", token=token))
        check(restored["last_response"] == answer, "Backend state restores the latest result")
        check(
            restored["definition"]["metric"]["semantic_version"] == answer["query_ir"]["semantic_version"],
            "Answer pins the displayed business definition version",
        )
        isolated = json.loads(request(API + "/state", token=other))
        check(isolated["source"] is None and isolated["last_response"] is None, "Sessions are isolated")
        request(API + "/upload", token=token, body=b"invalid", expected=422)
        preserved = json.loads(request(API + "/state", token=token))
        check(preserved["source"] == source, "Invalid upload preserves the previous source")
        request(API + "/chat", token=token, body={**question, "connector_id": "bigquery"}, expected=422)
        checks.append("Caller cannot select an internal connector")

        definition = initial["definitions"]
        check(definition["mode"] == "DEMO_SINGLE_USER", "Demo review authority is labeled explicitly")
        check(
            initial["connections"][1] == {"id": "bigquery", "status": "NOT_CONFIGURED"},
            "BigQuery placeholder does not report a live connection",
        )
        draft = json.loads(
            request(
                API + "/definitions/drafts",
                token=token,
                body={
                    "base_snapshot_id": definition["snapshot_id"],
                    "kind": "DIMENSION",
                    "definition_id": "REGION",
                    "name": "Region",
                    "definition": "Synthetic reporting territory assigned to each activation.",
                    "owner": "Demo Sales Analytics",
                    "aliases": ["territory"],
                    "reason": "Clarify territory meaning.",
                },
                expected=201,
            )
        )
        for action in ("submit", "approve", "publish"):
            draft = json.loads(
                request(
                    API + f"/definitions/drafts/{draft['draft_id']}/{action}",
                    token=token,
                    body={"expected_revision": draft["revision"], "note": "Reviewed synthetic definition."},
                )
            )
        current = json.loads(request(API + "/state", token=token))["definitions"]
        check(
            current["snapshot_id"] != definition["snapshot_id"], "Publication creates an immutable snapshot"
        )
        request(
            API + "/chat",
            token=token,
            body={**question, "definition_snapshot_id": definition["snapshot_id"]},
            expected=409,
        )
        checks.append("Stale business definitions reject a new question")
        fresh = json.loads(
            request(
                API + "/chat",
                token=token,
                body={**question, "definition_snapshot_id": current["snapshot_id"]},
            )
        )
        check(
            fresh["semantic_context"]["dimensions"][0]["definition_version"] == 2,
            "New answer cites the published dimension definition",
        )
        check(
            fresh["receipt"]["result_rows"] == receipt["result_rows"],
            "Definition metadata changes preserve the governed calculation",
        )

        # Remove one July day; a complete-month answer must abstain, never silently undercount.
        incomplete = "\n".join(
            line for line in raw_csv.decode().splitlines() if not line.startswith("2026-07-15,")
        )
        replacement = json.loads(request(API + "/upload", token=token, body=(incomplete + "\n").encode()))
        request(API + "/chat", token=token, body=question, expected=409)
        checks.append("Replacing a source rejects stale questions")
        replaced_state = json.loads(request(API + "/state", token=token))
        check(replaced_state["last_response"] is None, "Replacing a source removes the old answer")
        historical = json.loads(request(API + f"/history/{receipt['query_id']}/rerun", token=token, body=b""))
        check(
            historical["semantic_context"] == answer["semantic_context"],
            "Old run keeps its exact definitions",
        )
        check(
            historical["receipt"]["result_rows"] == receipt["result_rows"],
            "Old run reproduces its original CSV",
        )
        check(
            historical["agent_run"]["replayed_interpretation"]
            and historical["agent_run"]["usage"]["model_calls"] == 0,
            "Historical reproduction reuses its saved interpretation without model calls",
        )
        check(
            json.loads(request(API + "/state", token=token))["source"] == replacement,
            "Historical reproduction preserves the selected replacement source",
        )
        missing = json.loads(
            request(
                API + "/chat",
                token=token,
                body={**question, "source_fingerprint": replacement["source_fingerprint"]},
            )
        )
        check(missing["status"] == "SOURCE_NOT_READY" and missing["receipt"] is None, "Missing dates abstain")
        request(
            API + f"/definitions/snapshots/{definition['snapshot_id']}/revoke",
            token=token,
            body={
                "expected_revision": current["revision"],
                "note": "Withdraw original synthetic definition.",
            },
            expected=204,
        )
        request(API + f"/history/{receipt['query_id']}/rerun", token=token, body=b"", expected=409)
        checks.append("Revoked definitions cannot reproduce a saved answer")
    finally:
        request(API + "/clear", token=token, body=b"", expected=204)
        request(API + "/clear", token=other, body=b"", expected=204)
    request(API + "/state", token=token, expected=401)
    checks.append("Cleared sessions are inaccessible")
    return {"status": "passed", "checks": checks, "fixture_rows": len(rows), "july_total": 24676}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(run(args.base_url), indent=2))


if __name__ == "__main__":
    main()
