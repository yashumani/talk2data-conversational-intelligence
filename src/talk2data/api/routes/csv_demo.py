from __future__ import annotations

import asyncio
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from talk2data.domain.chat import DemoChatResponse
from talk2data.services.csv_workspace import CsvDemoWorkspace

router = APIRouter(prefix="/v1/demo/csv", tags=["isolated-csv-demo"])


class CsvQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    as_of: AwareDatetime
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    definition_snapshot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def workspace(request: Request) -> CsvDemoWorkspace:
    service = cast(CsvDemoWorkspace | None, request.app.state.csv_workspace)
    if service is None:
        raise HTTPException(404, "CSV demonstration is disabled.")
    return service


Workspace = Annotated[CsvDemoWorkspace, Depends(workspace)]
Token = Annotated[str, Header(alias="X-Demo-Session", min_length=40, max_length=64)]


@router.post("/sessions", status_code=201)
async def create_session(service: Workspace, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return {
        "session_token": service.create_session(),
        "expires_in_seconds": service.settings.session_ttl_seconds,
        "maximum_bytes": service.settings.maximum_bytes,
        "maximum_rows": service.settings.maximum_rows,
    }


@router.get("/state")
async def state(service: Workspace, token: Token, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    item = service.get(token)
    return service.state(item)


@router.post("/upload")
async def upload(request: Request, service: Workspace, token: Token) -> dict[str, object]:
    if request.headers.get("content-type", "").split(";")[0].lower() != "text/csv":
        raise HTTPException(415, "Send UTF-8 CSV as a raw text/csv request body.")
    async with service.lease(token) as item:
        chunks = bytearray()
        try:
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    if len(chunks) + len(chunk) > service.settings.maximum_bytes:
                        raise HTTPException(413, "CSV exceeds the upload byte limit.")
                    chunks.extend(chunk)
        except TimeoutError as exc:
            raise HTTPException(408, "CSV upload timed out.") from exc
        return await service.upload(item, bytes(chunks))


@router.post("/chat", response_model=DemoChatResponse)
async def chat(payload: CsvQuestion, service: Workspace, token: Token) -> DemoChatResponse:
    async with service.lease(token) as item:
        return await service.answer(
            item,
            question=payload.question,
            as_of=payload.as_of,
            source_fingerprint=payload.source_fingerprint,
            definition_snapshot_id=payload.definition_snapshot_id,
        )


@router.post("/clear", status_code=204)
async def clear(service: Workspace, token: Token) -> Response:
    service.clear(token)
    return Response(status_code=204)
