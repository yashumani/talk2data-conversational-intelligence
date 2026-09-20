from __future__ import annotations

import argparse
import re
import subprocess

SIGNOFF = re.compile(r"^Signed-off-by:\s*(.+?)\s*<([^>]+)>\s*$", re.MULTILINE | re.IGNORECASE)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, text=True, capture_output=True).stdout


def validate(base: str, head: str) -> int:
    commits = [value for value in git("rev-list", "--reverse", f"{base}..{head}").splitlines() if value]
    if not commits:
        raise SystemExit("No commits found in the requested DCO range")
    for commit in commits:
        name, email, body = git("show", "-s", "--format=%an%x00%ae%x00%B", commit).split("\x00", 2)
        normalized_author = (name.strip().casefold(), email.strip().casefold())
        signoffs = {(n.strip().casefold(), e.strip().casefold()) for n, e in SIGNOFF.findall(body)}
        if normalized_author not in signoffs:
            raise SystemExit(f"{commit}: missing exact author-matching Signed-off-by trailer")
    return len(commits)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    count = validate(args.base, args.head)
    print(f"Validated exact author-matching DCO sign-off for {count} commits.")
