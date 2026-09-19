from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict[str, object]:
    return json.loads((ROOT / "contracts" / name).read_text())


def validate() -> None:
    inventory = load("visualization_source_inventory.v1.json")
    taxonomy = load("visualization_source_taxonomy.v1.json")
    registry = load("visualization_registry.v1.json")
    targets = taxonomy["targets"]
    entries = registry["entries"]
    if not isinstance(targets, list) or len(targets) != 44 or len(set(targets)) != 44:
        raise SystemExit("Taxonomy must contain exactly 44 unique normalized targets")
    if inventory.get("union_count") != 44:
        raise SystemExit("Source inventory union_count must be 44")
    if not isinstance(entries, list) or len(entries) != 76:
        raise SystemExit("Registry must contain exactly 76 entries")
    ids = [entry["id"] for entry in entries]
    if len(set(ids)) != len(ids):
        raise SystemExit("Registry IDs must be unique")
    if any(entry["target"] not in targets for entry in entries):
        raise SystemExit("Every registry entry must map to a normalized target")
    batches = Counter(entry["batch"] for entry in entries)
    if [batches[number] for number in range(1, 9)] != [15, 10, 9, 10, 8, 8, 8, 8]:
        raise SystemExit(f"Unexpected batch sizes: {dict(batches)}")
    statuses = Counter(entry["status"] for entry in entries)
    if statuses != {"accepted": 15, "queued": 61}:
        raise SystemExit(f"Unexpected status totals: {dict(statuses)}")
    if any(entry["batch"] != 1 for entry in entries if entry["status"] == "accepted"):
        raise SystemExit("Only Batch 1 may be accepted in this candidate")
    catalog = (ROOT / "apps/web/src/visualizations/catalog.ts").read_text()
    for entry_id in ids:
        if f'["{entry_id}",' not in catalog:
            raise SystemExit(f"TypeScript catalog is missing {entry_id}")


if __name__ == "__main__":
    validate()
    print("Validated 44 taxonomy targets, 76 product types, 8 batches, 15 accepted, and 61 queued.")
