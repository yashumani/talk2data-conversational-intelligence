"""Server-created execution authority; no bearer token is stored in the queue."""

from pydantic import AwareDatetime, BaseModel, ConfigDict

from talk2data.domain.models import AccessContext


class ExecutionGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    access: AccessContext
    expires_at: AwareDatetime
