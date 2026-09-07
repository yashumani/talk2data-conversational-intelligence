from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from talk2data.connectors.errors import ConnectorValidationError
from talk2data.services.csv_workspace import DemoSessionExpired, DemoWorkspaceBusy


def install_demo_errors(app: FastAPI) -> None:
    @app.exception_handler(DemoSessionExpired)
    async def expired(_: Request, exc: DemoSessionExpired) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=401, headers={"Cache-Control": "no-store"})

    @app.exception_handler(DemoWorkspaceBusy)
    async def busy(_: Request, exc: DemoWorkspaceBusy) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ConnectorValidationError)
    async def invalid(_: Request, exc: ConnectorValidationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)
