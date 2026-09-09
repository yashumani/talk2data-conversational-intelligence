"""Shared durable HTTP/SSE contract; each application supplies its own trusted context."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from talk2data.domain.runs import TERMINAL, RunError, RunRequest, RunSnapshot
from talk2data.services.run_coordinator import RunCoordinator


@dataclass
class RunContext:
    owner: str
    scope: str
    coordinator: RunCoordinator
    authorize: Callable[[RunSnapshot], Awaitable[None]]
    submit: Callable[[RunRequest], RunSnapshot]
    manage_conversations: bool = True

    async def read(self, identifier: UUID) -> RunSnapshot:
        run = self.coordinator.store.read(self.owner, self.scope, identifier)
        await self.authorize(run)
        return run


async def stream_events(
    context: RunContext, identifier: UUID, after: int, request: Request
) -> AsyncIterator[str]:
    started = time.monotonic()
    while time.monotonic() - started < 20:
        if await request.is_disconnected():
            return
        try:
            run = await context.read(identifier)
        except Exception:
            yield "event: access_lost\ndata: {}\n\n"
            return
        events = context.coordinator.store.events(context.owner, context.scope, identifier, after)
        for event in events:
            try:
                await context.authorize(run)
            except Exception:
                yield "event: access_lost\ndata: {}\n\n"
                return
            # Events contain stages/status/usage; final answer bodies require an authorized snapshot GET.
            yield f"id: {identifier}:{event.sequence}\nevent: progress\ndata: {event.model_dump_json()}\n\n"
            after = event.sequence
        if run.status in TERMINAL and after == run.sequence:
            return
        yield ": heartbeat\n\n"
        await asyncio.sleep(0.25)


def prevent_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def run_router(prefix: str, dependency: Callable[..., RunContext]) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["durable-conversations"], dependencies=[Depends(prevent_caching)])

    @router.post("/conversations", status_code=201)
    async def create(context: RunContext = Depends(dependency)) -> object:
        if not context.manage_conversations:
            raise RunError("A CSV session owns one conversation. Start another session for a new workspace.")
        return context.coordinator.store.create_conversation(context.owner, context.scope)

    @router.get("/conversations")
    async def conversations(context: RunContext = Depends(dependency)) -> object:
        return context.coordinator.store.conversations(context.owner, context.scope)

    @router.get("/conversations/{identifier}")
    async def conversation(identifier: UUID, context: RunContext = Depends(dependency)) -> object:
        store = context.coordinator.store
        return {
            "conversation": store.conversation(context.owner, context.scope, identifier),
            "runs": [
                {"run_id": r.run_id, "status": r.status, "question": r.request.question}
                for r in store.runs(context.owner, context.scope, identifier)
            ],
        }

    @router.delete("/conversations/{identifier}", status_code=204)
    async def delete(identifier: UUID, context: RunContext = Depends(dependency)) -> Response:
        if not context.manage_conversations:
            raise RunError("Use Clear demo data to delete the CSV workspace and its conversation together.")
        context.coordinator.store.delete(context.owner, context.scope, identifier)
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @router.post("/runs", status_code=202)
    async def submit(payload: RunRequest, context: RunContext = Depends(dependency)) -> RunSnapshot:
        return context.submit(payload)

    @router.get("/runs/{identifier}")
    async def get(identifier: UUID, context: RunContext = Depends(dependency)) -> RunSnapshot:
        return await context.read(identifier)

    @router.post("/runs/{identifier}/cancel", status_code=202)
    async def cancel(identifier: UUID, context: RunContext = Depends(dependency)) -> RunSnapshot:
        await context.read(identifier)
        return context.coordinator.cancel(context.owner, context.scope, identifier)

    @router.get("/runs/{identifier}/events")
    async def events(
        identifier: UUID,
        request: Request,
        after: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, max_length=80),
        context: RunContext = Depends(dependency),
    ) -> StreamingResponse:
        await context.read(identifier)
        if last_event_id is not None:
            run_id, _, cursor = last_event_id.partition(":")
            if run_id != str(identifier) or not cursor.isdecimal():
                raise RunError("The replay cursor does not belong to this run.")
            after = int(cursor)
        context.coordinator.store.events(context.owner, context.scope, identifier, after)
        return StreamingResponse(
            stream_events(context, identifier, after, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router


def install_run_errors(app: FastAPI) -> None:
    @app.exception_handler(RunError)
    async def error(_: Request, exc: RunError) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc)}, status_code=exc.status_code, headers={"Cache-Control": "no-store"}
        )
