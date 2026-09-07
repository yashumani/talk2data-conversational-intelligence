"""Strict, bounded CSV ingestion. No warehouse, model, filesystem, or network access."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from talk2data.connectors.errors import ConnectorValidationError

REQUIRED_COLUMNS = frozenset({"date", "region", "channel", "activations"})
DIMENSION_COLUMNS = {
    "REGION": "region",
    "CHANNEL": "channel",
    "MARKET": "market",
    "STORE": "store",
    "PLAN": "plan",
}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | set(DIMENSION_COLUMNS.values())
SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")
REGIONS = frozenset({"NORTHEAST", "SOUTHEAST", "CENTRAL", "WEST"})
CHANNELS = frozenset({"RETAIL", "DIGITAL", "CARE"})


@dataclass(frozen=True)
class CsvDataset:
    columns: tuple[str, ...]
    rows: tuple[tuple[str | int, ...], ...]
    dates: frozenset[date]
    fingerprint: str
    uploaded_at: datetime

    @property
    def coverage_start(self) -> date:
        return min(self.dates)

    @property
    def coverage_end(self) -> date:
        return max(self.dates)

    @property
    def dimensions(self) -> list[str]:
        return [key for key, column in DIMENSION_COLUMNS.items() if column in self.columns]

    def describe(self) -> dict[str, object]:
        return {
            "source_kind": "csv_demo",
            "metric_ids": ["MOBILE_ACTIVATIONS"],
            "dimensions": self.dimensions,
            "row_count": len(self.rows),
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "source_fingerprint": self.fingerprint,
            "uploaded_at": self.uploaded_at.isoformat(),
        }


def parse_csv(raw: bytes, *, maximum_bytes: int, maximum_rows: int) -> CsvDataset:
    if not raw or len(raw) > maximum_bytes:
        raise ConnectorValidationError("CSV is empty or exceeds the upload byte limit.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConnectorValidationError("CSV must be UTF-8 text.") from exc
    if "\x00" in text:
        raise ConnectorValidationError("CSV must not contain null bytes.")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, [])
        if len(header) != len(set(header)) or not REQUIRED_COLUMNS <= set(header):
            raise ConnectorValidationError("CSV needs unique date, region, channel, activations headers.")
        if not set(header) <= ALLOWED_COLUMNS:
            raise ConnectorValidationError("CSV contains unsupported columns; use the supplied template.")
        rows: list[tuple[str | int, ...]] = []
        dates: set[date] = set()
        keys: set[tuple[str | int, ...]] = set()
        for number, values in enumerate(reader, start=2):
            if len(rows) >= maximum_rows:
                raise ConnectorValidationError("CSV exceeds the row limit.")
            if len(values) != len(header):
                raise ConnectorValidationError(f"Row {number} has the wrong number of cells.")
            record: dict[str, str | int] = dict(zip(header, values, strict=True))
            raw_date = str(record["date"])
            try:
                day = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ConnectorValidationError(f"Row {number} needs a YYYY-MM-DD date.") from exc
            if raw_date != day.isoformat():
                raise ConnectorValidationError(f"Row {number} needs a YYYY-MM-DD date.")
            amount = str(record["activations"])
            if not re.fullmatch(r"[0-9]{1,10}", amount) or int(amount) > 1_000_000_000:
                raise ConnectorValidationError(f"Row {number} needs a non-negative integer activation count.")
            record["activations"] = int(amount)
            for column in set(header) - {"date", "activations"}:
                value = str(record[column]).strip().upper()
                if not SAFE_VALUE.fullmatch(value):
                    raise ConnectorValidationError(f"Row {number} has an invalid dimension value.")
                record[column] = value
            if record["region"] not in REGIONS or record["channel"] not in CHANNELS:
                raise ConnectorValidationError(f"Row {number} has an unknown demo region or channel.")
            key = tuple(record[column] for column in sorted(header) if column != "activations")
            if key in keys:
                raise ConnectorValidationError(f"Row {number} repeats a date/dimension key.")
            keys.add(key)
            dates.add(day)
            rows.append(tuple(record[column] for column in header))
    except csv.Error as exc:
        raise ConnectorValidationError("CSV has invalid quoting or an oversized cell.") from exc
    if not rows:
        raise ConnectorValidationError("CSV needs at least one data row.")
    return CsvDataset(
        columns=tuple(header),
        rows=tuple(rows),
        dates=frozenset(dates),
        fingerprint=hashlib.sha256(raw).hexdigest(),
        uploaded_at=datetime.now(UTC),
    )
