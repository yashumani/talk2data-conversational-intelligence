from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from talk2data.api.run_routes import RunContext, stream_events
from talk2data.domain.runs import RunError
from talk2data.services.run_coordinator import RunCoordinator
from talk2data.services.run_store import RunStore
from tests.test_durable_runs import request


async def test_progress_stream_stops_between_events_when_access_is_revoked() -> None:
    store = RunStore()
    run = store.enqueue("owner", "scope", request(store), "source")
    store.start(run.run_id)
    revoked = False

    async def authorize(_: Any) -> None:
        if revoked:
            raise RunError("Access revoked", 403)

    async def connected() -> bool:
        return False

    context = RunContext("owner", "scope", RunCoordinator(store), authorize, lambda _: run)
    stream = stream_events(context, run.run_id, 0, SimpleNamespace(is_disconnected=connected))
    assert "id: " + str(run.run_id) + ":1" in await anext(stream)
    revoked = True
    assert await anext(stream) == "event: access_lost\ndata: {}\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    store.close()


@pytest.mark.parametrize("disconnected,denied", [(True, False), (False, True), (False, False)])
async def test_progress_disconnect_authorization_and_keepalive_deadline(
    monkeypatch: pytest.MonkeyPatch, disconnected: bool, denied: bool
) -> None:
    store = RunStore()
    run = store.enqueue("owner", "scope", request(store), "source")
    store.start(run.run_id)

    async def authorize(_: Any) -> None:
        if denied:
            raise RunError("Access denied", 403)

    async def is_disconnected() -> bool:
        return disconnected

    async def tick(_: float) -> None:
        pass

    context = RunContext("owner", "scope", RunCoordinator(store), authorize, lambda _: run)
    # Patch only this generator's time source; do not alter the event loop's real clock.
    monkeypatch.setattr("talk2data.api.run_routes.time", SimpleNamespace(monotonic=iter([0, 0, 21]).__next__))
    monkeypatch.setattr("talk2data.api.run_routes.asyncio", SimpleNamespace(sleep=tick))
    output = [
        value
        async for value in stream_events(
            context, run.run_id, 2, SimpleNamespace(is_disconnected=is_disconnected)
        )
    ]
    assert output == (
        [] if disconnected else ["event: access_lost\ndata: {}\n\n"] if denied else [": heartbeat\n\n"]
    )
    store.close()
