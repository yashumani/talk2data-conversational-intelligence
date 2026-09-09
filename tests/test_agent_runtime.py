from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from talk2data.core.claude_config import AgentLimits
from talk2data.services.agent_runtime import AgentFailure, AgentRun


async def test_specialists_run_once_in_order_with_registered_tools() -> None:
    run = AgentRun()
    assert await run.async_step("SEMANTIC_RESOLVER", lambda: asyncio.sleep(0, result="metric")) == "metric"
    assert run.sync("QUERY_PLANNER", lambda: "approved plan") == "approved plan"
    assert await run.async_step("QUERY_EXECUTOR", lambda: asyncio.sleep(0, result=31)) == 31
    assert run.sync("RESULT_VERIFIER", lambda: True)
    assert run.sync("ANSWER_COMPOSER", lambda: "31 activations") == "31 activations"
    assert [s.sequence for s in run.report.steps] == [1, 2, 3, 4, 5]
    assert all(s.status == "SUCCEEDED" and s.duration_ms >= 0 for s in run.report.steps)
    assert run.report.steps[2].tool == "execute_bound_query"
    with pytest.raises(AgentFailure) as error:
        run.sync("QUERY_EXECUTOR", lambda: pytest.fail("Duplicate execution"))
    assert error.value.code == "STEP_BUDGET"


async def test_wrong_order_and_step_limit_prevent_execution() -> None:
    run = AgentRun(AgentLimits(maximum_steps=1))
    with pytest.raises(AgentFailure) as error:
        run.sync("QUERY_PLANNER", lambda: pytest.fail("Skipped authorization"))
    assert error.value.code == "INVALID_STAGE"
    await run.async_step("SEMANTIC_RESOLVER", lambda: asyncio.sleep(0))
    with pytest.raises(AgentFailure) as error:
        run.sync("QUERY_PLANNER", lambda: pytest.fail("Over budget"))
    assert error.value.code == "STEP_BUDGET"


@pytest.mark.parametrize("kind", ["expired", "during"])
async def test_deadlines_stop_unfinished_specialists(kind: str) -> None:
    run = AgentRun()
    run.deadline = time.monotonic() + (-1 if kind == "expired" else 0.02)
    stopped = asyncio.Event()

    async def wait() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    with pytest.raises(AgentFailure) as error:
        await run.finish(lambda: run.async_step("SEMANTIC_RESOLVER", wait))
    assert error.value.code == "RUN_DEADLINE" and error.value.report
    assert error.value.report.status == "FAILED"
    if kind == "during":
        assert stopped.is_set()


async def test_stage_timeout_is_sanitized_without_an_outer_coordinator() -> None:
    run = AgentRun()
    run.deadline = time.monotonic() + 0.02
    with pytest.raises(AgentFailure) as error:
        await run.async_step("SEMANTIC_RESOLVER", lambda: asyncio.Event().wait())
    assert error.value.code == "RUN_DEADLINE"
    assert run.report.steps[0].status == "FAILED"


@pytest.mark.parametrize("async_stage", [False, True])
async def test_unexpected_stage_failures_are_not_exposed(async_stage: bool) -> None:
    run = AgentRun()

    def fail() -> Any:
        raise ValueError("private SQL and credential")

    async def fail_async() -> Any:
        return fail()

    async def operation() -> None:
        if async_stage:
            await run.async_step("SEMANTIC_RESOLVER", fail_async)
        else:
            run.sync("SEMANTIC_RESOLVER", fail)

    with pytest.raises(AgentFailure) as error:
        await run.finish(operation)
    assert error.value.code == "RUN_FAILED"
    assert "private SQL" not in str(error.value)
    assert error.value.report and error.value.report.steps[0].status == "FAILED"


async def test_cancellation_propagates_to_the_active_stage() -> None:
    run = AgentRun()
    started = asyncio.Event()

    async def wait() -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(run.finish(lambda: run.async_step("SEMANTIC_RESOLVER", wait)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run.report.status == "CANCELLED" and run.report.steps[0].status == "CANCELLED"


@pytest.mark.parametrize(
    "second_input,limits",
    [
        (100, AgentLimits(maximum_model_calls=1)),
        (1500, AgentLimits(maximum_model_calls=2, maximum_total_tokens=2000)),
    ],
)
def test_model_call_and_token_reservations_are_hard_dispatch_limits(
    second_input: int, limits: AgentLimits
) -> None:
    run = AgentRun(limits)
    run.reserve(500, 512)
    with pytest.raises(AgentFailure) as error:
        run.reserve(second_input, 512)
    assert error.value.code == "MODEL_BUDGET"
    assert run.report.usage.model_calls == 1 and run.report.usage.reserved_tokens == 1012
