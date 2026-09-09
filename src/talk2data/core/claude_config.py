"""Claude configuration remains independent from all data connectors."""

from typing import Literal

from pydantic import Field

from talk2data.core.language_config import AgentLimits as AgentLimits
from talk2data.core.language_config import CsvLanguageSettings as CsvLanguageSettings
from talk2data.core.language_config import LanguageConfiguration


class ClaudeConfiguration(LanguageConfiguration):
    provider: Literal["claude"] = "claude"
    model: str | None = Field(default=None, pattern=r"^claude-[a-z0-9-]{3,100}$")
    secret_ref: str = Field(default="env://T2D_CLAUDE_API_KEY", pattern=r"^env://[A-Z][A-Z0-9_]{1,100}$")
