"""Create and restore validated offline state bundles without overwriting existing files."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from talk2data.operations.database import MaintenanceError, checksum, connect, offline, validate


class BackupFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    created_at: AwareDatetime
    state: BackupFile
    definitions: BackupFile | None = None


def copy_database(source: Path, destination: Path, kind: Literal["state", "definitions"]) -> BackupFile:
    with destination.open("xb"):
        destination.chmod(0o600)
    with closing(connect(source)) as original, closing(sqlite3.connect(destination)) as copied:
        validate(original, kind)
        original.backup(copied)
        copied.execute("PRAGMA journal_mode=DELETE")
        validate(copied, kind)
    return BackupFile(sha256=checksum(destination), bytes=destination.stat().st_size)


def create_bundle(state: Path, destination: Path, definitions: Path | None = None) -> BackupManifest:
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise MaintenanceError("Backup requires a new absolute destination directory.")
    if definitions is not None and (
        not definitions.is_absolute() or definitions.resolve() == state.resolve()
    ):
        raise MaintenanceError("A separate definitions file must have a distinct absolute path.")
    with offline(state):
        destination.mkdir(mode=0o700)
        try:
            result = BackupManifest(
                created_at=datetime.now(UTC),
                state=copy_database(state, destination / "state.sqlite3", "state"),
                definitions=None
                if definitions is None
                else copy_database(definitions, destination / "definitions.sqlite3", "definitions"),
            )
            manifest = destination / "manifest.json"
            manifest.write_text(result.model_dump_json(indent=2))
            manifest.chmod(0o600)
            return result
        except BaseException:
            shutil.rmtree(destination)
            raise


def restore_bundle(bundle: Path, destination: Path) -> BackupManifest:
    if (
        not bundle.is_absolute()
        or bundle.is_symlink()
        or not destination.is_absolute()
        or destination.exists()
        or destination.is_symlink()
    ):
        raise MaintenanceError("Restore requires an absolute bundle and a new destination directory.")
    if bundle.resolve() in destination.resolve().parents:
        raise MaintenanceError("Restore cannot modify the original backup directory.")
    try:
        if (bundle / "manifest.json").is_symlink():
            raise ValueError("A regular manifest is required.")
        manifest = BackupManifest.model_validate_json((bundle / "manifest.json").read_bytes())
        for name in ("state", "definitions"):
            record = getattr(manifest, name)
            if record is None:
                continue
            source = bundle / (name + ".sqlite3")
            if (
                source.is_symlink()
                or source.stat().st_size != record.bytes
                or checksum(source) != record.sha256
            ):
                raise ValueError("Backup digest mismatch.")
    except (OSError, ValueError):
        raise MaintenanceError("Backup manifest or file integrity failed.") from None
    destination.mkdir(mode=0o700)
    try:
        for kind in ("state", "definitions"):
            record = getattr(manifest, kind)
            if record is None:
                continue
            target = destination / (kind + ".sqlite3")
            with (bundle / (kind + ".sqlite3")).open("rb") as input_stream, target.open("xb") as output:
                target.chmod(0o600)
                shutil.copyfileobj(input_stream, output)
            if checksum(target) != record.sha256:
                raise MaintenanceError("Backup changed during restore.")
            with closing(connect(target)) as database:
                validate(database, kind)
        return manifest
    except BaseException:
        shutil.rmtree(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    create = sub.add_parser("create")
    create.add_argument("--state", type=Path, required=True)
    create.add_argument("--definitions", type=Path)
    create.add_argument("--destination", type=Path, required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (
            create_bundle(args.state, args.destination, args.definitions)
            if args.operation == "create"
            else restore_bundle(args.bundle, args.destination)
        )
    except (OSError, ValueError, sqlite3.Error, MaintenanceError):
        print(json.dumps({"status": "FAILED", "reason": "MAINTENANCE_NOT_COMPLETED"}))
        raise SystemExit(1) from None
    print(
        json.dumps(
            {"status": "VERIFIED", "operation": args.operation, "manifest": result.model_dump(mode="json")}
        )
    )


if __name__ == "__main__":
    main()
