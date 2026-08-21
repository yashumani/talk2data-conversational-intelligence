from __future__ import annotations

import ast
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpaceBundleManifest:
    source_revision: str
    files: dict[str, str]


def build_space_bundle(
    repository_root: Path,
    destination: Path,
    *,
    source_revision: str = "working-tree",
) -> SpaceBundleManifest:
    """Build a self-contained Gradio Space without copying local state or secrets."""

    repository_root = repository_root.resolve()
    destination = destination.resolve()
    template = repository_root / "hf_space"
    package = repository_root / "src" / "talk2data"
    if not template.is_dir():
        raise FileNotFoundError(f"Hugging Face template directory is missing: {template}")
    if not package.is_dir():
        raise FileNotFoundError(f"Talk2Data package directory is missing: {package}")

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    _copy_tree(template, destination)
    _copy_tree(package, destination / "talk2data")

    license_file = repository_root / "LICENSE"
    if license_file.is_file():
        shutil.copy2(license_file, destination / "LICENSE")

    errors = validate_space_bundle(destination)
    if errors:
        raise ValueError("Invalid Hugging Face Space bundle: " + "; ".join(errors))

    file_hashes = {
        candidate.relative_to(destination).as_posix(): _sha256(candidate)
        for candidate in sorted(destination.rglob("*"))
        if candidate.is_file() and candidate.name != "DEPLOYMENT_MANIFEST.json"
    }
    manifest = SpaceBundleManifest(source_revision=source_revision, files=file_hashes)
    (destination / "DEPLOYMENT_MANIFEST.json").write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_space_bundle(bundle: Path) -> list[str]:
    errors: list[str] = []
    required = {
        "README.md",
        "app.py",
        "requirements.txt",
        "talk2data/__init__.py",
        "talk2data/resources/domain_packs/telecom-demo.yaml",
    }
    present = {
        candidate.relative_to(bundle).as_posix()
        for candidate in bundle.rglob("*")
        if candidate.is_file()
    }
    for required_path in sorted(required - present):
        errors.append(f"missing required file {required_path}")

    readme = bundle / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        for marker in ("sdk: gradio", "app_file: app.py", "python_version:"):
            if marker not in text:
                errors.append(f"README.md is missing {marker!r}")

    forbidden_suffixes = {".db", ".sqlite", ".sqlite3", ".pyc"}
    forbidden_names = {".env", "id_rsa", "id_ed25519"}
    for candidate in bundle.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(bundle).as_posix()
        if candidate.name in forbidden_names or candidate.suffix.lower() in forbidden_suffixes:
            errors.append(f"forbidden runtime or secret file {relative}")
        if candidate.suffix == ".py":
            try:
                ast.parse(candidate.read_text(encoding="utf-8"), filename=relative)
            except SyntaxError as exc:
                errors.append(f"invalid Python in {relative}: {exc}")
    return errors


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
