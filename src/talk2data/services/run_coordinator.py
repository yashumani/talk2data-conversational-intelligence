"""Accepted jobs outlive HTTP connections; terminal states and events share a durable journal."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from talk2data.domain.agents import AgentRunReport
from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.runs import RunError, RunRequest, RunSnapshot
from talk2data.services.agent_runtime import AgentFailure
from talk2data.services.run_store import RunStore

Observer = Callable[[AgentRunReport], None]
Operation = Callable[[Observer], Awaitable[DemoChatResponse]]


class RunCoordinator:
    def __init__(self, store: RunStore, maximum_active: int = 8) -> None:
        self.store, self.maximum_active = store, maximum_active
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.cleanup: dict[UUID, Callable[[], None]] = {}
        self.closing = False

    def submit(
        self,
        owner: str,
        scope: str,
        request: RunRequest,
        binding: str,
        operation: Operation,
        authorize: Callable[[], Awaitable[None]],
        accepted: Callable[[], None] = lambda: None,
        released: Callable[[], None] = lambda: None,
    ) -> RunSnapshot:
        existing = self.store.existing(owner, scope, request)
        if existing is not None:
            return existing
        if self.closing or len(self.tasks) >= self.maximum_active:
            raise RunError("Run capacity is occupied. Retry the same request ID later.", 429)
        run = self.store.enqueue(owner, scope, request, binding)
        accepted()
        self.cleanup[run.run_id] = released
        self.tasks[run.run_id] = asyncio.create_task(self._execute(run.run_id, operation, authorize))
        return run

    async def _execute(
        self, identifier: UUID, operation: Operation, authorize: Callable[[], Awaitable[None]]
    ) -> None:
        try:
            if not self.store.start(identifier):
                self.store.finish(identifier, "CANCELLED", message="Cancelled before execution.")
                return
            await authorize()
            result = await operation(lambda report: self.store.progress(identifier, report))
            await authorize()
            self.store.finish(identifier, "COMPLETED", result=result, message=result.message)
        except asyncio.CancelledError:
            self.store.finish(
                identifier,
                "INTERRUPTED" if self.closing else "CANCELLED",
                code="WORKER_STOPPED" if self.closing else None,
                message="Worker stopped; no automatic rerun."
                if self.closing
                else "Cancellation confirmed; no answer released.",
            )
        except AgentFailure as exc:
            self.store.finish(identifier, "FAILED", code=exc.code, message=str(exc))
        except Exception:
            self.store.finish(
                identifier, "FAILED", code="RUN_FAILED", message="The run failed; no answer was released."
            )
        finally:
            self.tasks.pop(identifier, None)
            self.cleanup.pop(identifier)()

    def cancel(self, owner: str, scope: str, identifier: UUID) -> RunSnapshot:
        before = self.store.read(owner, scope, identifier)
        run = self.store.cancel(owner, scope, identifier)
        task = self.tasks.get(identifier)
        if task is not None and before.status == "RUNNING":
            task.cancel()
        if task is None:
            run = self.store.finish(identifier, "CANCELLED", message="Cancelled before execution.")
        return run

    async def close(self) -> None:
        self.closing = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Tasks cancelled before their coroutine started still need a terminal journal entry.
        self.store.recover()
        for released in self.cleanup.values():
            released()
        self.cleanup.clear()
        self.tasks.clear()
