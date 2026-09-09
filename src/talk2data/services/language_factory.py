"""Select exactly one configured language provider; never infer or fall back between providers."""

from __future__ import annotations

import json
from pathlib import Path

from talk2data.core.claude_config import ClaudeConfiguration
from talk2data.core.gemini_config import GeminiConfiguration
from talk2data.services.claude_interpreter import ClaudeRuntime
from talk2data.services.claude_transport import ClaudeTransport
from talk2data.services.gemini_interpreter import GeminiRuntime
from talk2data.services.gemini_transport import GeminiTransport
from talk2data.services.language_contract import LanguageRuntime

ProviderConfiguration = ClaudeConfiguration | GeminiConfiguration
ProviderTransport = ClaudeTransport | GeminiTransport


def load_language_configuration(path: Path) -> ProviderConfiguration:
    if not path.is_absolute():
        raise ValueError("Language configuration requires an absolute private file path.")
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, dict):
        raise ValueError("Language configuration must be an object.")
    provider = raw.get("provider", "claude")
    if provider == "gemini":
        return GeminiConfiguration.model_validate(raw)
    if provider == "claude":
        return ClaudeConfiguration.model_validate(raw)
    raise ValueError("The language provider is not supported.")


def build_language_runtime(
    config: ProviderConfiguration | None = None, transport: ProviderTransport | None = None
) -> LanguageRuntime:
    if isinstance(config, GeminiConfiguration):
        if transport is not None and not isinstance(transport, GeminiTransport):
            raise ValueError("Gemini requires its own transport.")
        return GeminiRuntime(config, transport)
    if transport is not None and not isinstance(transport, ClaudeTransport):
        raise ValueError("Claude requires its own transport.")
    return ClaudeRuntime(config, transport)
