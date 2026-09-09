"""Two-phase HTTP acceptance across an actual API restart, using synthetic CSV only.

The private checkpoint contains a demo capability. Keep it outside the repository and
never upload it as a CI artifact. The JSON printed to stdout contains check labels only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import time
from collections import defaultdict
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

API = "/v1/demo/csv"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}


class Acceptance:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.checks: list[str] = []

    def check(self, condition: bool, label: str) -> None:
        if not condition:
            raise RuntimeError("Durable CSV acceptance failed: " + label)
        self.checks.append(label)

    def request(
        self,
        path: str,
        token: str | None = None,
        body: bytes | dict[str, Any] | None = None,
        expected: int = 200,
        cursor: str | None = None,
    ) -> bytes:
        headers = {} if token is None else {"X-Demo-Session": token}
        if cursor is not None:
            headers["Last-Event-ID"] = cursor
        if isinstance(body, dict):
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        else:
            data = body
            if body is not None:
                headers["Content-Type"] = "text/csv"
        request = Request(self.base_url + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=5) as response:
                status, raw = response.status, response.read()
                if path.startswith(API + "/runs"):
                    if response.headers.get("Cache-Control") != "no-store":
                        raise RuntimeError("Run response permits caching.")
        except HTTPError as exc:
            status, raw = exc.code, exc.read()
        if status != expected:
            raise RuntimeError(f"{path}: expected HTTP {expected}, received {status}")
        return raw

    def ready(self) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                readiness = json.loads(self.request("/health/ready"))
                if readiness.get("status") == "ready":
                    return
            except (HTTPException, OSError, RuntimeError):
                pass
            time.sleep(0.25)
        raise RuntimeError("The API did not become ready after restart.")

    def terminal(self, token: str, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            run: dict[str, Any] = json.loads(self.request(API + "/runs/" + run_id, token))
            if run["status"] in TERMINAL:
                return run
            time.sleep(0.05)
        raise RuntimeError("The synthetic run did not finish within the acceptance deadline.")

    def events(self, token: str, run: dict[str, Any], after: int = 0) -> list[dict[str, Any]]:
        raw = self.request(
            API + f"/runs/{run['run_id']}/events", token, cursor=f"{run['run_id']}:{after}"
        ).decode()
        self.check("result_rows" not in raw, "Stream omits result rows")
        self.check(run["request"]["question"] not in raw, "Stream omits the question body")
        events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
        self.check(
            [event["sequence"] for event in events] == list(range(after + 1, run["sequence"] + 1)),
            "Event replay is ordered and complete",
        )
        self.check(all(event["run_id"] == run["run_id"] for event in events), "Events keep their run ID")
        return events

    def prepare(self, checkpoint: Path) -> None:
        self.ready()
        raw_csv = self.request("/workspace/samples/mobile-activations.csv")
        rows = list(csv.DictReader(io.StringIO(raw_csv.decode())))
        expected: defaultdict[str, int] = defaultdict(int)
        for row in rows:
            if row["date"].startswith("2026-07-"):
                expected[row["region"]] += int(row["activations"])
        self.check(len(rows) == 736 and sum(expected.values()) == 24676, "Independent fixture totals match")
        token = json.loads(self.request(API + "/sessions", body=b"", expected=201))["session_token"]
        try:
            source = json.loads(self.request(API + "/upload", token, raw_csv))
            state = json.loads(self.request(API + "/state", token))
            self.check(state["sync"]["durable"] is True, "Persistent workspace configuration is active")
            request = {
                "client_request_id": str(uuid4()),
                "conversation_id": state["sync"]["conversation"]["conversation_id"],
                "expected_revision": state["sync"]["conversation"]["revision"],
                "question": "What were mobile activations by region last month?",
                "as_of": "2026-08-01T12:00:00Z",
                "source_fingerprint": source["source_fingerprint"],
                "definition_snapshot_id": state["definitions"]["snapshot_id"],
            }
            accepted = json.loads(self.request(API + "/runs", token, request, expected=202))
            run = self.terminal(token, accepted["run_id"])
            self.check(run["status"] == "COMPLETED", "Asynchronous run reaches completion")
            answer = run["result"]
            self.check(answer["status"] == "ANSWERED", "The completed run contains an answer")
            self.check(
                {row["REGION"]: row["value"] for row in answer["receipt"]["result_rows"]} == dict(expected),
                "Run result matches independently calculated regional totals",
            )
            self.check(run["source_binding"] == source["source_fingerprint"], "Run binds the uploaded source")
            self.check(
                answer["agent_run"]["usage"]["model_calls"] == 0, "Rules-only acceptance makes no model calls"
            )
            self.check(
                json.loads(self.request(API + "/runs", token, request, expected=202)) == run,
                "Duplicate submission returns the same completed record",
            )
            self.events(token, run)
            saved = {"token": token, "request": request, "run": run, "source": source, "checks": self.checks}
            with os.fdopen(os.open(checkpoint, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "w") as stream:
                os.chmod(checkpoint, 0o600)
                json.dump(saved, stream)
        except BaseException:
            self.request(API + "/clear", token, b"", expected=204)
            raise

    def verify(self, checkpoint: Path) -> None:
        saved = json.loads(checkpoint.read_text())
        self.checks = saved["checks"]
        token, original = saved["token"], saved["run"]
        self.ready()
        try:
            state = json.loads(self.request(API + "/state", token))
            self.check(state["source"] == saved["source"], "Restart restores the exact CSV source")
            self.check(
                state["last_response"] == original["result"], "Restart restores the exact saved answer"
            )
            conversation = state["sync"]["conversation"]
            self.check(
                conversation["conversation_id"] == saved["request"]["conversation_id"]
                and conversation["revision"] == 1
                and len(state["sync"]["runs"]) == 1,
                "Restart preserves conversation identity and its single accepted run",
            )
            self.check(
                self.terminal(token, original["run_id"]) == original,
                "Restart preserves the complete run record",
            )
            self.check(
                json.loads(self.request(API + "/runs", token, saved["request"], expected=202)) == original,
                "Lost-acknowledgment retry after restart does not create a second run",
            )
            self.events(token, original, after=2)
            self.check(
                not self.events(token, original, after=original["sequence"]),
                "Fully acknowledged replay is empty",
            )
            other = json.loads(self.request(API + "/sessions", body=b"", expected=201))["session_token"]
            try:
                self.request(API + "/runs/" + original["run_id"], other, expected=404)
                self.check(True, "Another workspace cannot read the saved run")
            finally:
                self.request(API + "/clear", other, b"", expected=204)
            raw_csv = self.request("/workspace/samples/mobile-activations.csv")
            rows = list(csv.DictReader(io.StringIO(raw_csv.decode())))
            for row in rows:
                row["activations"] = str(int(row["activations"]) + 1)
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            replacement = json.loads(self.request(API + "/upload", token, output.getvalue().encode()))
            self.check(replacement != saved["source"], "Replacement selects a distinct accepted source")
            self.check(
                json.loads(self.request(API + "/runs", token, saved["request"], expected=202)) == original,
                "Retry keeps the historical source and result after replacement",
            )
            state = json.loads(self.request(API + "/state", token))
            self.check(
                state["source"] == replacement
                and state["last_response"] is None
                and len(state["sync"]["runs"]) == 1,
                "Historical replay leaves the new source selected without showing a stale current answer",
            )
        finally:
            self.request(API + "/clear", token, b"", expected=204)
            checkpoint.unlink(missing_ok=True)
        self.request(API + "/runs/" + original["run_id"], token, expected=401)
        self.check(True, "Clearing the workspace revokes access to its durable runs")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "verify"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--checkpoint-file", type=Path, required=True)
    args = parser.parse_args()
    acceptance = Acceptance(args.base_url)
    if args.phase == "prepare":
        acceptance.prepare(args.checkpoint_file)
    else:
        acceptance.verify(args.checkpoint_file)
    print(
        json.dumps(
            {
                "passed": True,
                "phase": args.phase,
                "check_count": len(acceptance.checks),
                "checks": acceptance.checks,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
