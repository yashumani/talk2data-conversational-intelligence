from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update the Talk2Data Hugging Face Space.")
    parser.add_argument("--space-id", required=True, help="Hugging Face Space ID in owner/name form")
    parser.add_argument("--bundle", type=Path, default=Path("dist/hf-space"))
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit("HF_TOKEN is required and must have write access to the target Space.")
    if not args.bundle.is_dir():
        raise SystemExit(f"Space bundle does not exist: {args.bundle}")

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(
        repo_id=args.space_id,
        repo_type="space",
        space_sdk="gradio",
        private=args.private,
        exist_ok=True,
    )
    api.upload_folder(
        repo_id=args.space_id,
        repo_type="space",
        folder_path=str(args.bundle),
        commit_message="Deploy Talk2Data governed local-model demonstration",
    )
    print(f"Published https://huggingface.co/spaces/{args.space_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
