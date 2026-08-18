from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

QUESTIONS = [
    ("What was postpaid churn by plan last month?", "ANSWERED"),
    (
        "Compare mobile activations in Northeast last month to the previous period.",
        "ANSWERED",
    ),
    ("What were mobile activations this month?", "SOURCE_NOT_READY"),
    ("What was ARPA last month?", "NO_SOURCE"),
    ("What is our restaurant food-cost margin by location?", "OUT_OF_DOMAIN"),
]

ACCESS = {
    "tenant_id": "demo-telecom",
    "user_id": "demo-smoke",
    "roles": ["TALK2DATA_ADMIN"],
    "departments": ["BUSINESS_INTELLIGENCE"],
    "regions": ["NORTH_AMERICA"],
    "business_units": ["CONSUMER"],
    "classification_clearance": "RESTRICTED",
    "permitted_actions": [
        "ASK_BUSINESS_QUESTIONS",
        "READ_AGGREGATED_DATA",
        "USE_EXTERNAL_CONTEXT",
    ],
}


def run(base_url: str, require_ollama: bool) -> int:
    session_id: str | None = None
    with httpx.Client(base_url=base_url, timeout=240) as client:
        readiness = client.get("/health/ready")
        readiness.raise_for_status()
        ready_body = readiness.json()
        print(json.dumps(ready_body, indent=2))
        if require_ollama and ready_body["components"]["ollama"]["status"] != "ready":
            print("Ollama is not ready.", file=sys.stderr)
            return 1

        for question, expected_status in QUESTIONS:
            response = client.post(
                "/v1/chat/demo",
                json={
                    "question": question,
                    "access_context": ACCESS,
                    "session_id": session_id,
                    "use_llm": True,
                    "include_debug": True,
                    "as_of": "2026-08-17T12:00:00Z",
                },
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            session_id = str(body["session_id"])
            actual_status = str(body["status"])
            print(f"\nQ: {question}\nA: {body['message']}\nStatus: {actual_status}")
            if actual_status != expected_status:
                print(f"Expected {expected_status}, got {actual_status}.", file=sys.stderr)
                return 1
            if actual_status == "ANSWERED":
                if body["verification"]["status"] != "VERIFIED":
                    print("Answer was not verified.", file=sys.stderr)
                    return 1
                if not body["receipt"]["result_hash"]:
                    print("Answer did not include a result hash.", file=sys.stderr)
                    return 1
                if require_ollama and body["decision"]["interpreter_mode"] != "OLLAMA_AND_RULES":
                    print("Real Ollama interpretation was not used.", file=sys.stderr)
                    return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the Talk2Data demonstration runtime.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--allow-rules-fallback", action="store_true")
    arguments = parser.parse_args()
    return run(arguments.base_url.rstrip("/"), not arguments.allow_rules_fallback)


if __name__ == "__main__":
    raise SystemExit(main())
