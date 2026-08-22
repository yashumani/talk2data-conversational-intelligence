from __future__ import annotations

import argparse
import os
from pathlib import Path

from talk2data.deployment.huggingface import build_space_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a self-contained Talk2Data Gradio Space.")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--destination", type=Path, default=Path("dist/hf-space"))
    args = parser.parse_args()
    revision = os.getenv("GITHUB_SHA", "working-tree")
    manifest = build_space_bundle(
        args.repository_root,
        args.destination,
        source_revision=revision,
    )
    print(f"Built {len(manifest.files)} files at {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
