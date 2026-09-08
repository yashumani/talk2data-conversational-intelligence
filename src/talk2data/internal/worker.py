"""Wire the existing governed query pipeline to fenced, credential-free queue records."""

import asyncio
from uuid import uuid5

from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.runs import RunError, now, principal
from talk2data.internal.runtime import InternalQueryRuntime
from talk2data.services.distributed_runs import DistributedWorker
from talk2data.services.identity import Entitlements
from talk2data.services.postgres_runs import ClaimedRun, PostgresRunStore
from talk2data.services.run_coordinator import Observer


def create_worker(runtime: InternalQueryRuntime, entitlements: Entitlements) -> DistributedWorker:
    if not isinstance(runtime.run_store, PostgresRunStore):
        raise ValueError("Distributed workers require the shared state adapter.")

    async def authorize(job: ClaimedRun) -> None:
        original = job.grant.access
        current = await asyncio.to_thread(entitlements.resolve, original.user_id)
        if (
            current != original
            or job.grant.expires_at <= now()
            or job.run.source_binding != runtime.source_binding
        ):
            raise RunError("Execution authorization expired or changed.", 403)
        owner, scope = principal("internal", current)
        runtime.run_store.read(owner, scope, job.run.run_id)
        runtime.definitions[current.tenant_id].resolve(current, job.run.request.definition_snapshot_id)

    async def operation(job: ClaimedRun, observer: Observer) -> DemoChatResponse:
        payload = job.run.request
        return await runtime.answer(
            request_id=uuid5(payload.conversation_id, str(payload.client_request_id)),
            question=payload.question,
            as_of=payload.as_of,
            access=job.grant.access,
            definition_snapshot_id=payload.definition_snapshot_id,
            observer=observer,
            require_current=False,
        )

    return DistributedWorker(
        runtime.run_store, runtime.source_binding, operation, authorize, runtime.maximum_active
    )
