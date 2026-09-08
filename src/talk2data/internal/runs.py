"""Internal run authority is revalidated before dispatch, release and every replay read."""

from typing import cast
from uuid import uuid5

from fastapi import Request

from talk2data.api.run_routes import RunContext, run_router
from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.runs import RunError, RunRequest, RunSnapshot, principal
from talk2data.internal.routes import identity, runtime
from talk2data.services.identity import IdentityVerifier
from talk2data.services.policy import ASK_ACTION, READ_DATA_ACTION
from talk2data.services.run_coordinator import Observer


def context(request: Request) -> RunContext:
    access, service = identity(request), runtime(request)
    if not {ASK_ACTION, READ_DATA_ACTION} <= access.permitted_actions:
        raise RunError("Question and data access must both be authorized.", 403)
    owner, scope = principal("internal", access)
    verifier = cast(IdentityVerifier, request.app.state.verifier)
    token = cast(str, request.state.identity_token)

    async def authorize(run: RunSnapshot) -> None:
        current = await verifier.verify(token)
        if current != access or run.source_binding != service.source_binding:
            raise RunError("Authorization or the approved source binding changed.", 403)
        service.definitions[access.tenant_id].resolve(access, run.request.definition_snapshot_id)

    def submit(payload: RunRequest) -> RunSnapshot:
        existing = service.run_store.existing(owner, scope, payload)
        if existing is not None:
            # Source changes cannot make a previous request point at a new physical binding.
            if existing.source_binding != service.source_binding:
                raise RunError("The approved internal source changed.")
            service.definitions[access.tenant_id].resolve(access, existing.request.definition_snapshot_id)
            return existing
        if payload.source_fingerprint is not None:
            raise RunError("Internal runs use only the server-owned BigQuery binding.", 422)
        service.definitions[access.tenant_id].resolve(
            access, payload.definition_snapshot_id, require_current=True
        )

        async def check() -> None:
            if await verifier.verify(token) != access:
                raise RunError("Authorization changed during execution.", 403)
            service.definitions[access.tenant_id].resolve(access, payload.definition_snapshot_id)

        async def operation(observer: Observer) -> DemoChatResponse:
            return await service.answer(
                request_id=uuid5(payload.conversation_id, str(payload.client_request_id)),
                question=payload.question,
                as_of=payload.as_of,
                access=access,
                definition_snapshot_id=payload.definition_snapshot_id,
                observer=observer,
                require_current=False,
            )

        return service.runs.submit(owner, scope, payload, service.source_binding, operation, check)

    return RunContext(owner, scope, service.runs, authorize, submit)


router = run_router("/v1/internal", context)
