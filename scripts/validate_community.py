from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "LICENSE",
    "DCO",
    "VERSION",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "GOVERNANCE.md",
    "SECURITY.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
    ".github/CODEOWNERS",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/support_question.yml",
    "docs/PUBLIC_ALPHA_RELEASE_CHECKLIST.md",
    "docs/VERSIONING.md",
)


def validate() -> None:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing:
        raise SystemExit("Missing community files: " + ", ".join(missing))

    version = (ROOT / "VERSION").read_text().strip()
    if version != "0.7.0-alpha.2":
        raise SystemExit(f"Unexpected release version: {version}")
    expected = {
        "pyproject.toml": 'version = "0.7.0a2"',
        "apps/web/package.json": '"version": "0.7.0-alpha.2"',
        "CHANGELOG.md": "0.7.0-alpha.2",
        "docs/PUBLIC_ALPHA_RELEASE_CHECKLIST.md": "Current decision: GO for the scoped `0.7.0-alpha.2`",
    }
    for path, marker in expected.items():
        if marker not in (ROOT / path).read_text():
            raise SystemExit(f"{path} is missing release marker {marker!r}")

    package = json.loads((ROOT / "apps/web/package.json").read_text())
    lock = json.loads((ROOT / "apps/web/package-lock.json").read_text())
    if package["version"] != lock["version"] or lock["packages"][""]["version"] != package["version"]:
        raise SystemExit("Web package and lockfile versions disagree")

    contributing = (ROOT / "CONTRIBUTING.md").read_text()
    if "git commit -s" not in contributing or "Do not sign for another person" not in contributing:
        raise SystemExit("CONTRIBUTING.md must explain DCO sign-off ownership")
    security = (ROOT / "SECURITY.md").read_text()
    if "Do not open a public issue for suspected vulnerabilities" not in security:
        raise SystemExit("SECURITY.md must keep vulnerability reports private")


if __name__ == "__main__":
    validate()
    print("Validated community policies, licensing, contribution forms, and alpha release metadata.")
