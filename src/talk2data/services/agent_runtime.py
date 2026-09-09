"""Bounded sequential specialists. Model output never selects a callable or grants authority."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from talk2data.core.language_config import AgentLimits
from talk2data.domain.agents import AgentRole, AgentRunReport, AgentStep
from talk2data.domain.models import InterpretationResult

T = TypeVar("T")
TOOLS: dict[AgentRole, str] = {
    "SEMANTIC_RESOLVER": "interpret_governed_question",
    "QUERY_PLANNER": "compile_business_query",
    "QUERY_EXECUTOR": "execute_bound_query",
    "RESULT_VERIFIER": "verify_query_receipt",
    "ANSWER_COMPOSER": "compose_certified_answer",
}


class AgentFailure(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.code, self.status_code = code, status_code
        self.report: AgentRunReport | None = None
        self.retry_after: str | None = None
        self.retryable: bool = False


class AgentRun:
    def __init__(
        self, limits: AgentLimits | None = None, observer: Callable[[AgentRunReport], None] | None = None
    ) -> None:
        self.limits = limits or AgentLimits()
        self.deadline = time.monotonic() + self.limits.deadline_seconds
        self.report = AgentRunReport()
        self.interpretation: InterpretationResult | None = None
        self.last_reservation = 0
        self.observer = observer

    def notify(self) -> None:
        if self.observer is not None:
            self.observer(self.report.model_copy(deep=True))

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AgentFailure(
                "RUN_DEADLINE", "The request deadline was reached; no answer was released.", 504
            )
        return remaining

    def _start(self, role: AgentRole) -> tuple[AgentStep, float]:
        self.remaining()
        if len(self.report.steps) >= self.limits.maximum_steps or any(
            s.role == role for s in self.report.steps
        ):
            raise AgentFailure("STEP_BUDGET", "The specialist execution budget was reached.")
        expected = list(TOOLS)
        if expected.index(role) != len(self.report.steps):
            raise AgentFailure("INVALID_STAGE", "The requested specialist transition is not permitted.")
        step = AgentStep(role=role, tool=TOOLS[role], sequence=len(self.report.steps) + 1)
        self.report.steps.append(step)
        self.notify()
        return step, time.monotonic()

    def sync(self, role: AgentRole, operation: Callable[[], T]) -> T:
        step, started = self._start(role)
        try:
            result = operation()
            self.remaining()
            step.status = "SUCCEEDED"
            return result
        except Exception:
            step.status = "FAILED"
            raise
        finally:
            step.duration_ms = max(0, int((time.monotonic() - started) * 1000))
            self.notify()

    async def async_step(self, role: AgentRole, operation: Callable[[], Awaitable[T]]) -> T:
        step, started = self._start(role)
        try:
            remaining = self.remaining()
            result = await asyncio.wait_for(operation(), timeout=remaining)
            step.status = "SUCCEEDED"
            return result
        except asyncio.CancelledError:
            step.status = "CANCELLED"
            self.report.status = "CANCELLED"
            raise
        except TimeoutError as exc:
            step.status = "FAILED"
            raise AgentFailure(
                "RUN_DEADLINE", "The request deadline was reached; cancellation was requested.", 504
            ) from exc
        except Exception:
            step.status = "FAILED"
            raise
        finally:
            step.duration_ms = max(0, int((time.monotonic() - started) * 1000))
            self.notify()

    def reserve(self, input_tokens: int, output_tokens: int) -> None:
        self.remaining()
        usage = self.report.usage
        required = input_tokens + output_tokens
        if (
            usage.model_calls >= self.limits.maximum_model_calls
            or usage.reserved_tokens + required > self.limits.maximum_total_tokens
        ):
            raise AgentFailure("MODEL_BUDGET", "The language-model usage budget was reached.")
        usage.model_calls += 1
        usage.usage_complete = False
        usage.counted_input_tokens += input_tokens
        usage.reserved_tokens += required
        self.last_reservation = required
        self.notify()

    async def finish(self, operation: Callable[[], Awaitable[T]]) -> T:
        try:
            remaining = self.remaining()
            return await asyncio.wait_for(operation(), timeout=remaining)
        except AgentFailure as exc:
            self.report.status, self.report.error_code = "FAILED", exc.code
            exc.report = self.report.model_copy(deep=True)
            raise
        except TimeoutError as exc:
            failure = AgentFailure(
                "RUN_DEADLINE", "The request deadline was reached; cancellation was requested.", 504
            )
            self.report.status, self.report.error_code = "FAILED", failure.code
            failure.report = self.report.model_copy(deep=True)
            raise failure from exc
        except asyncio.CancelledError:
            self.report.status = "CANCELLED"
            raise
        except Exception as exc:
            failure = AgentFailure("RUN_FAILED", "The governed request failed; no answer was released.", 500)
            self.report.status, self.report.error_code = "FAILED", failure.code
            failure.report = self.report.model_copy(deep=True)
            raise failure from exc
