"""Opt-in gemini live acceptance using the common synthetic CSV benchmark."""

import os
from pathlib import Path

import pytest

from talk2data.core.gemini_config import GeminiConfiguration
from talk2data.services.gemini_interpreter import GeminiRuntime
from tests.language_acceptance import run_live_acceptance

pytestmark = pytest.mark.live_gemini


async def test_live_gemini_grounding_numbers_abstention_and_replay(tmp_path: Path) -> None:
    if os.environ.get("T2D_RUN_LIVE_GEMINI") != "1":
        pytest.skip("Set T2D_RUN_LIVE_GEMINI=1 with approved configuration for real gemini acceptance.")
    config = GeminiConfiguration.load(Path(os.environ["T2D_GEMINI_ACCEPTANCE_CONFIG"]))
    artifact = Path(os.environ.get("T2D_GEMINI_ACCEPTANCE_REPORT", str(tmp_path / "gemini-acceptance.json")))
    await run_live_acceptance(GeminiRuntime(config), artifact)
