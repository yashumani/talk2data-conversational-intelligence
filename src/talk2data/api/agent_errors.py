"""Consistent, sanitized provider and bounded-run failures for both isolated profiles."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from talk2data.services.agent_runtime import AgentFailure


def install_agent_errors(app: FastAPI) -> None:
    @app.exception_handler(AgentFailure)
    async def failure(_: Request, exc: AgentFailure) -> JSONResponse:
        return JSONResponse(
            {
                "detail": str(exc),
                "code": exc.code,
                "agent_run": None if exc.report is None else exc.report.model_dump(mode="json"),
            },
            status_code=exc.status_code,
            headers={"Cache-Control": "no-store"},
        )
