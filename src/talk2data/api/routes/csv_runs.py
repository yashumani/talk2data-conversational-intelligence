"""CSV run endpoints resolve only the caller's isolated demo session."""

from fastapi import Request

from talk2data.api.routes.csv_demo import workspace
from talk2data.api.run_routes import RunContext, run_router
from talk2data.domain.runs import RunError, RunSnapshot, principal


def context(request: Request) -> RunContext:
    service = workspace(request)
    tokens = request.headers.getlist("X-Demo-Session")
    if len(tokens) != 1 or not 40 <= len(tokens[0]) <= 64:
        raise RunError("One demo session token is required.", 401)
    token = tokens[0]
    item = service.get(token)
    owner, scope = principal("csv", service._access(item))

    async def authorize(run: RunSnapshot) -> None:
        service.check_run(token, run.run_id)

    return RunContext(
        owner, scope, service.runs, authorize, lambda payload: service.submit_run(token, payload), False
    )


router = run_router("/v1/demo/csv", context)
