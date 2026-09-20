from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(source_sha: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise SystemExit("source SHA must be exactly 40 lowercase hexadecimal characters")
    site = ROOT / "site"
    workspace = site / "workspace"
    if not (workspace / "index.html").is_file():
        raise SystemExit("Run the dedicated Pages build before preparing the release")
    version = (ROOT / "VERSION").read_text().strip()
    (site / "release.json").write_text(
        json.dumps({"source_sha": source_sha, "version": version}, sort_keys=True, indent=2) + "\n"
    )
    licenses = site / "licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "LICENSE", licenses / "LICENSE")
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", licenses / "THIRD_PARTY_NOTICES.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    prepare(parser.parse_args().source_sha)
    print("Prepared exact-SHA Pages release receipt and license notices.")
