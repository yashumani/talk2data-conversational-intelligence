from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol

from pydantic import SecretStr


class SecretResolutionError(RuntimeError):
    """Raised when a configured secret reference cannot be resolved safely."""


class SecretResolver(Protocol):
    def resolve(self, secret_ref: str) -> SecretStr: ...


class EnvironmentSecretResolver:
    """Resolves env:// references without exposing names or values in errors."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = os.environ if environment is None else environment

    def resolve(self, secret_ref: str) -> SecretStr:
        provider, separator, secret_name = secret_ref.partition("://")
        if provider != "env" or not separator or not secret_name:
            raise SecretResolutionError("The connector secret provider is not supported.")
        value = self._environment.get(secret_name, "").strip()
        if not value:
            raise SecretResolutionError("The configured connector secret is unavailable.")
        return SecretStr(value)
