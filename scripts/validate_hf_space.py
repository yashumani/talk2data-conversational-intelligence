from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from talk2data.deployment.huggingface import build_space_bundle, validate_space_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Hugging Face Space bundle.")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()

    if args.bundle is not None:
        errors = validate_space_bundle(args.bundle)
    else:
        with tempfile.TemporaryDirectory(prefix="talk2data-hf-") as directory:
            destination = Path(directory) / "space"
            build_space_bundle(args.repository_root, destination)
            errors = validate_space_bundle(destination)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Hugging Face Space bundle validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
