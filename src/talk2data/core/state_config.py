"""Private shared-state configuration, independent of analytical data connections."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SharedStateSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dsn_secret_ref: str = Field(pattern=r"^env://[A-Z][A-Z0-9_]*$")
    allow_insecure_loopback: bool = False
    lease_seconds: int = Field(default=30, ge=5, le=120)
    heartbeat_seconds: float = Field(default=2, ge=0.1, le=10)
    poll_seconds: float = Field(default=0.5, ge=0.05, le=5)
    maximum_pending: int = Field(default=128, ge=1, le=4096)
    maximum_running: int = Field(default=16, ge=1, le=128)
    maximum_running_per_tenant: int = Field(default=4, ge=1, le=32)
    maximum_conversations: int = Field(default=4096, ge=1, le=100000)

    @model_validator(mode="after")
    def bounded_lease(self) -> Self:
        if self.heartbeat_seconds * 3 >= self.lease_seconds:
            raise ValueError("Heartbeat must be shorter than one third of the worker lease.")
        if self.maximum_running_per_tenant > self.maximum_running:
            raise ValueError("Tenant capacity cannot exceed global execution capacity.")
        return self
