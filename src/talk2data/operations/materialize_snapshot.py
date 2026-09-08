"""Operator CLI for BigQuery-to-Parquet materialization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from talk2data.core.internal_config import InternalRuntimeConfig
from talk2data.domain.bigquery_mapping import BigQueryCatalog
from talk2data.services.bigquery_snapshot_sdk import GoogleSnapshotTransport
from talk2data.services.snapshot_materializer import SnapshotMaterializer


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize approved BigQuery views as local Parquet.")
    parser.add_argument("--config", type=Path, required=True)
    arguments = parser.parse_args()
    config = InternalRuntimeConfig.load(arguments.config)
    if config.bigquery is None or config.parquet is None:
        raise SystemExit("Materialization requires both bigquery and parquet configuration blocks.")
    catalog = BigQueryCatalog.load(config.bigquery_catalog_path)
    transport = GoogleSnapshotTransport(config.bigquery)
    materializer = SnapshotMaterializer(config.parquet, transport)
    try:
        manifests = [materializer.materialize(mapping) for mapping in catalog.mappings]
    finally:
        transport.close()
    print(json.dumps([item.model_dump(mode="json") for item in manifests], sort_keys=True))


if __name__ == "__main__":
    main()
