from __future__ import annotations

import json
import re
from collections import Counter
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

SITE = Path("site")
REQUIRED = [
    SITE / "index.html",
    SITE / "app.js",
    SITE / "ui.js",
    SITE / "styles" / "base.css",
    SITE / "styles" / "chat.css",
    SITE / "styles" / "inspector.css",
    SITE / "styles" / "setup.css",
    SITE / "styles" / "responsive.css",
    SITE / "config.js",
    SITE / ".nojekyll",
    SITE / "demo" / "index.html",
    SITE / "setup" / "index.html",
    SITE / "setup" / "app.js",
]

CODESPACES_URL = (
    "https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1"
)


class DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.password_inputs = 0
        self.inline_scripts = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if identifier := values.get("id"):
            self.ids.append(identifier)
        if tag == "input" and str(values.get("type", "")).lower() == "password":
            self.password_inputs += 1
        if tag == "script" and not values.get("src"):
            self.inline_scripts += 1


def parse_document(path: Path) -> DocumentParser:
    parser = DocumentParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def require_markers(content: str, markers: tuple[str, ...], *, label: str) -> None:
    for marker in markers:
        if marker not in content:
            raise SystemExit(f"Required {label} marker is missing: {marker!r}")


def require_ids(parser: DocumentParser, required: set[str], *, label: str) -> None:
    duplicates = sorted(identifier for identifier, count in Counter(parser.ids).items() if count > 1)
    if duplicates:
        raise SystemExit(f"Duplicate IDs in {label}: {', '.join(duplicates)}")
    missing = sorted(required.difference(parser.ids))
    if missing:
        raise SystemExit(f"Required IDs missing from {label}: {', '.join(missing)}")


def main() -> int:
    missing = [str(path) for path in REQUIRED if not path.exists()]
    if missing:
        raise SystemExit("Missing GitHub Pages assets: " + ", ".join(missing))

    html = (SITE / "index.html").read_text(encoding="utf-8")
    normalized_html = unescape(html)
    script = (SITE / "app.js").read_text(encoding="utf-8")
    ui_script = (SITE / "ui.js").read_text(encoding="utf-8")
    styles = "\n".join(
        (SITE / "styles" / name).read_text(encoding="utf-8")
        for name in (
            "base.css",
            "chat.css",
            "inspector.css",
            "setup.css",
            "responsive.css",
        )
    )
    setup_html = (SITE / "setup" / "index.html").read_text(encoding="utf-8")
    normalized_setup_html = unescape(setup_html)
    setup_script = (SITE / "setup" / "app.js").read_text(encoding="utf-8")
    config = (SITE / "config.js").read_text(encoding="utf-8")

    require_markers(
        normalized_html,
        (
            'data-ui="open-webui-inspired"',
            "Talk2Data",
            "What do you want to know about your business?",
            "Connect runtime",
            "Evidence inspector",
            CODESPACES_URL,
            "./setup/",
            "./styles/base.css",
            "./styles/chat.css",
            "./styles/inspector.css",
            "./styles/setup.css",
            "./styles/responsive.css",
            "./config.js",
            "./ui.js",
            "./app.js",
        ),
        label="chat page",
    )
    main_parser = parse_document(SITE / "index.html")
    require_ids(
        main_parser,
        {
            "sidebar",
            "new-chat",
            "open-connection",
            "history-search",
            "history-list",
            "runtime",
            "welcome",
            "examples",
            "chat",
            "form",
            "question",
            "send",
            "inspector",
            "runtime-detail",
            "ai",
            "decision",
            "claims",
            "receipt",
            "plan",
            "connection-dialog",
            "api-base",
            "connect",
        },
        label="chat page",
    )
    if main_parser.inline_scripts:
        raise SystemExit("The chat page must use external scripts under the strict CSP.")

    if 'fetch("/v1/' in script or "fetch('/v1/" in script:
        raise SystemExit("Static client must use the configured API base URL.")
    require_markers(
        script,
        (
            "`${state.apiBase}/v1/chat/demo`",
            "`${state.apiBase}/health/ready`",
            "browserPrincipal()",
            "renderHistory()",
            "renderPanel(data)",
            "window.Talk2DataUI.activateInspectorTab",
        ),
        label="chat client",
    )
    if "talk2data.chat" in script.lower() and "localstorage" in script.lower():
        raise SystemExit("Conversation content must not be persisted in local storage.")

    require_markers(
        ui_script,
        (
            "window.Talk2DataUI",
            "toggleSidebar",
            "toggleInspector",
            "activateInspectorTab",
            "showDialog",
            "showToast",
        ),
        label="shared UI shell",
    )
    require_markers(
        styles,
        (
            ".app-shell",
            ".sidebar",
            ".workspace",
            ".composer",
            ".inspector",
            ".settings-layout",
            "@media (max-width: 960px)",
            "@media (max-width: 720px)",
        ),
        label="shared stylesheet",
    )

    require_markers(
        normalized_setup_html,
        (
            'data-ui="open-webui-inspired"',
            "Build your Talk2Data runtime",
            "Secret environment variable",
            "Validate package",
            "Download ZIP",
            CODESPACES_URL,
            "../styles/base.css",
            "../styles/chat.css",
            "../styles/inspector.css",
            "../styles/setup.css",
            "../styles/responsive.css",
            "../config.js",
            "../ui.js",
            "./app.js",
        ),
        label="setup page",
    )
    setup_parser = parse_document(SITE / "setup" / "index.html")
    require_ids(
        setup_parser,
        {
            "setup-status",
            "api-base",
            "connect",
            "setup-form",
            "project-name",
            "project-slug",
            "model-id",
            "schema-name",
            "table-name",
            "secret-name",
            "preview",
            "download",
            "status-detail",
            "template-detail",
            "package-id",
            "files",
            "warnings",
            "request-preview",
        },
        label="setup page",
    )
    if setup_parser.password_inputs:
        raise SystemExit("The public setup wizard must never request a database password.")
    if "actual password" not in setup_html.lower() and "never a password" not in setup_html.lower():
        raise SystemExit("The setup wizard must explain the secret boundary.")
    if setup_parser.inline_scripts:
        raise SystemExit("The setup page must use external scripts under the strict CSP.")

    require_markers(
        setup_script,
        (
            "`${apiBase}/health/ready`",
            "`${apiBase}/v1/runtime-packages/template`",
            "`${apiBase}/v1/runtime-packages/preview`",
            "`${apiBase}/v1/runtime-packages/download`",
            "browserPrincipal()",
            "env://${elements.secretName.value.trim()}",
        ),
        label="setup client",
    )

    if "feat/github-native-runtime" in "\n".join(
        (normalized_html, normalized_setup_html, script, setup_script)
    ):
        raise SystemExit("Published UI links must target the main branch, not a retired feature branch.")

    match = re.fullmatch(
        r"window\.T2D_PUBLIC_API_BASE_URL = (.+);\n?",
        config,
    )
    if match is None:
        raise SystemExit("config.js does not match the expected assignment format.")
    value = json.loads(match.group(1))
    if not isinstance(value, str):
        raise SystemExit("The public API base URL must be a string.")

    print("Open WebUI-inspired Talk2Data chat and setup validation passed.")
    print(f"Configured public API: {value or 'not set'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
