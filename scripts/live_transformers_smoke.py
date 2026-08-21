from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import cast

from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import InterpreterMode
from talk2data.services.interpreter import (
    CompositeQuestionInterpreter,
    HeuristicQuestionInterpreter,
    OllamaQuestionInterpreter,
)
from talk2data.services.transformers_interpreter import (
    TransformersConfiguration,
    TransformersQuestionInterpreter,
)


async def run() -> int:
    model_id = os.getenv("T2D_HF_MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct")
    cache_dir = Path(os.getenv("HF_HOME", "/tmp/talk2data-hf-cache"))
    registry = DomainPackRegistry()
    registry.load()
    pack = registry.get("demo-telecom")

    provider = TransformersQuestionInterpreter(
        TransformersConfiguration(
            model_id=model_id,
            max_new_tokens=256,
            device="cpu",
            cache_dir=cache_dir,
        )
    )
    await provider.preload()
    composite = CompositeQuestionInterpreter(
        HeuristicQuestionInterpreter(),
        cast(OllamaQuestionInterpreter, provider),
        ollama_required=True,
    )
    result = await composite.interpret(
        "What was postpaid churn by plan last month?",
        pack,
        use_llm=True,
    )

    payload = result.model_dump(mode="json")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if result.mode != InterpreterMode.OLLAMA_AND_RULES:
        raise RuntimeError(f"Expected real local-model interpretation, got {result.mode}")
    if "POSTPAID_CHURN" not in result.proposal.candidate_metric_ids:
        raise RuntimeError("The live model did not resolve POSTPAID_CHURN")
    if "PLAN" not in result.proposal.candidate_dimensions:
        raise RuntimeError("The live model did not resolve PLAN as a dimension")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
