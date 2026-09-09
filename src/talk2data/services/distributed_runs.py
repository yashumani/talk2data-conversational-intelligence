"""Internal queue admission and independent workers with database-owned fencing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import UUID

from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.execution import ExecutionGrant
from talk2data.domain.runs import RunError, RunRequest, RunSnapshot
from talk2data.services.postgres_runs import ClaimedRun, PostgresRunStore
from talk2data.services.run_coordinator import Observer


class DistributedCoordinator:
    def __init__(self, store: PostgresRunStore) -> None:
        self.store = store
        self.closing = False

    def submit(
        self, owner: str, scope: str, request: RunRequest, binding: str, grant: ExecutionGrant
    ) -> RunSnapshot:
        if self.closing:
            raise RunError("Admission is stopping. Retry the same request ID.", 503)
        return self.store.enqueue(owner, scope, request, binding, grant)

    def cancel(self, owner: str, scope: str, identifier: UUID) -> RunSnapshot:
        return self.store.cancel(owner, scope, identifier)

    async def close(self) -> None:
        self.closing = True


class DistributedWorker:
    def __init__(
        self,
        store: PostgresRunStore,
        binding: str,
        operation: Callable[[ClaimedRun, Observer], Awaitable[DemoChatResponse]],
        authorize: Callable[[ClaimedRun], Awaitable[None]],
        maximum_active: int = 4,
    ) -> None:
        self.store, self.binding = store, binding
        self.operation, self.authorize, self.maximum_active = operation, authorize, maximum_active
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.jobs: dict[UUID, ClaimedRun] = {}
        self.stop = asyncio.Event()
        self.loop_task: asyncio.Task[None] | None = None
        self.healthy = False

    def start(self) -> None:
        self.loop_task = asyncio.create_task(self._poll())

    async def tick(self) -> None:
        while len(self.tasks) < self.maximum_active and not self.stop.is_set():
            job = await asyncio.to_thread(self.store.claim, self.binding)
            if job is None:
                break
            self.jobs[job.run.run_id] = job
            self.tasks[job.run.run_id] = asyncio.create_task(self._execute(job))

    async def _poll(self) -> None:
        while not self.stop.is_set():
            try:
                await self.tick()
                self.healthy = True
            except Exception:
                self.healthy = False
            with suppress(TimeoutError):
                await asyncio.wait_for(self.stop.wait(), self.store.settings.poll_seconds)

    async def _monitor(self, job: ClaimedRun, task: asyncio.Future[DemoChatResponse]) -> None:
        try:
            while not task.done():
                await asyncio.sleep(self.store.settings.heartbeat_seconds)
                await self.authorize(job)
                if not await asyncio.to_thread(self.store.heartbeat, job):
                    raise RunError("Execution was cancelled or its authority expired.")
        except Exception:
            task.cancel()

    async def _execute(self, job: ClaimedRun) -> None:
        task: asyncio.Future[DemoChatResponse] | None = None
        monitor: asyncio.Task[None] | None = None
        try:
            await self.authorize(job)
            if not await asyncio.to_thread(self.store.heartbeat, job):
                raise RunError("Execution was cancelled before dispatch.")
            task = asyncio.ensure_future(self.operation(job, lambda report: self.store.progress(job, report)))
            monitor = asyncio.create_task(self._monitor(job, task))
            result = await task
            await self.authorize(job)
            await asyncio.to_thread(
                self.store.finish, job, "COMPLETED", result=result, message=result.message
            )
        except asyncio.CancelledError:
            with suppress(RunError):
                await asyncio.to_thread(
                    self.store.finish,
                    job,
                    "INTERRUPTED",
                    code="WORKER_STOPPED",
                    message="Execution stopped; no automatic rerun.",
                )
        except Exception:
            with suppress(RunError):
                await asyncio.to_thread(
                    self.store.finish,
                    job,
                    "FAILED",
                    code="RUN_FAILED",
                    message="The run failed; no answer was released.",
                )
        finally:
            for child in (task, monitor):
                if child is not None:
                    child.cancel()
            await asyncio.gather(
                *(child for child in (task, monitor) if child is not None), return_exceptions=True
            )
            self.tasks.pop(job.run.run_id, None)
            self.jobs.pop(job.run.run_id, None)

    async def close(self) -> None:
        self.stop.set()
        if self.loop_task is not None:
            await self.loop_task
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        # Also fence jobs whose task was cancelled before its coroutine entered.
        for job in list(self.jobs.values()):
            with suppress(RunError):
                await asyncio.to_thread(self.store.finish, job, "INTERRUPTED", code="WORKER_STOPPED")
        self.tasks.clear()
        self.jobs.clear()
        self.healthy = False
