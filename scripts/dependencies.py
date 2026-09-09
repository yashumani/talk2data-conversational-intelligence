"""Generate, check and install hash-locked dependencies without activating providers."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPILER_VERSION = "0.12.8"
PROFILES = ("runtime", "internal", "dev")
INPUTS = ("pyproject.toml", "requirements/build.in", "requirements/dev.in")
MANIFEST = "requirements/manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(root: Path) -> dict[str, object]:
    paths = (*INPUTS, *(f"requirements/{profile}.txt" for profile in PROFILES))
    return {"compiler": f"uv=={COMPILER_VERSION}", "sha256": {path: digest(root / path) for path in paths}}


def check(root: Path) -> None:
    recorded = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if recorded != manifest(root):
        raise ValueError("Dependency inputs or locks changed; run python scripts/dependencies.py lock.")


def generate(root: Path, *, upgrade: bool = False) -> None:
    compiler = shutil.which("uv")
    if compiler is None:
        raise ValueError(f"Install the reviewed uv=={COMPILER_VERSION} lock compiler first.")
    version = subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout
    if version.split()[:2] != ["uv", COMPILER_VERSION]:
        raise ValueError(f"Lock generation requires uv=={COMPILER_VERSION}; found {version.strip()}.")
    for profile in ("dev", "runtime", "internal"):
        command = [
            compiler,
            "pip",
            "compile",
            "pyproject.toml",
            "requirements/build.in",
            "--universal",
            "--python-version",
            "3.11",
            "--generate-hashes",
            "--no-header",
            "--no-annotate",
            "--quiet",
            "--output-file",
            f"requirements/{profile}.txt",
        ]
        if profile == "dev":
            command.extend(["requirements/dev.in", "--extra", "dev"])
            if upgrade:
                command.append("--upgrade")
        else:
            # Test and ship identical versions of shared packages.
            command.extend(["--constraint", "requirements/dev.txt"])
            if profile == "internal":
                command.extend(["--extra", "internal"])
        subprocess.run(command, cwd=root, check=True, stdout=subprocess.DEVNULL)
    (root / MANIFEST).write_text(json.dumps(manifest(root), indent=2) + "\n", encoding="utf-8")


def install(root: Path, profile: str) -> None:
    if profile not in PROFILES:
        raise ValueError(f"Unsupported dependency profile: {profile}")
    check(root)
    pip = [sys.executable, "-m", "pip"]
    subprocess.run(
        [
            *pip,
            "install",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            f"requirements/{profile}.txt",
        ],
        cwd=root,
        check=True,
    )
    project = "." if profile == "runtime" else f".[{profile}]"
    command = [*pip, "install", "--no-deps", "--no-build-isolation"]
    if profile == "dev":
        command.append("--editable")
    subprocess.run([*command, project], cwd=root, check=True)
    subprocess.run([*pip, "check"], cwd=root, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    lock_parser = subparsers.add_parser("lock")
    lock_parser.add_argument("--upgrade", action="store_true")
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("profile", choices=PROFILES)
    args = parser.parse_args()
    try:
        if args.command == "lock":
            generate(ROOT, upgrade=args.upgrade)
        elif args.command == "install":
            install(ROOT, args.profile)
        else:
            check(ROOT)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Dependency {args.command} failed: {exc}", file=sys.stderr)
        return 1
    print(f"Dependency {args.command} completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
