from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from talk2data.services.definition_governance import DefinitionDenied, DefinitionNotFound
from talk2data.services.definition_store import DefinitionConflict, DefinitionUnavailable


def install_definition_errors(app: FastAPI) -> None:
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        status = (
            403 if isinstance(exc, DefinitionDenied) else 404 if isinstance(exc, DefinitionNotFound) else 409
        )
        return JSONResponse({"detail": str(exc)}, status_code=status, headers={"Cache-Control": "no-store"})

    for kind in (DefinitionDenied, DefinitionNotFound, DefinitionConflict, DefinitionUnavailable):
        app.add_exception_handler(kind, handler)
