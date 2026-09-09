"""Opt-in claude live acceptance using the common synthetic CSV benchmark."""

import os
from pathlib import Path

import pytest

from talk2data.core.claude_config import ClaudeConfiguration
from talk2data.services.claude_interpreter import ClaudeRuntime
from tests.language_acceptance import run_live_acceptance

pytestmark = pytest.mark.live_claude


async def test_live_claude_grounding_numbers_abstention_and_replay(tmp_path: Path) -> None:
    if os.environ.get("T2D_RUN_LIVE_CLAUDE") != "1":
        pytest.skip("Set T2D_RUN_LIVE_CLAUDE=1 with approved configuration for real claude acceptance.")
    config = ClaudeConfiguration.load(Path(os.environ["T2D_CLAUDE_ACCEPTANCE_CONFIG"]))
    artifact = Path(os.environ.get("T2D_CLAUDE_ACCEPTANCE_REPORT", str(tmp_path / "claude-acceptance.json")))
    await run_live_acceptance(ClaudeRuntime(config), artifact)
