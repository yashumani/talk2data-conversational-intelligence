"""Cryptographic identity verification and private server-owned authorization grants."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Self

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from talk2data.core.internal_config import IdentitySettings
from talk2data.domain.models import AccessContext


class IdentityRejected(RuntimeError):
    pass


class IdentityUnavailable(RuntimeError):
    pass


class EntitlementFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = Field(min_length=1)
    issuer: str
    bindings: list[AccessContext]

    @model_validator(mode="after")
    def unique_subjects(self) -> Self:
        if len({entry.user_id for entry in self.bindings}) != len(self.bindings):
            raise ValueError("Each subject must have one unambiguous server-owned tenant binding.")
        return self


class EntitlementStore:
    def __init__(self, path: Path, issuer: str) -> None:
        self.path, self.issuer = path, issuer

    def resolve(self, subject: str) -> AccessContext:
        try:
            # Re-read atomically published private grants so removed access is not cached.
            payload = self.path.read_bytes()
            if len(payload) > 1_000_000:
                raise ValueError("Entitlement file exceeds its configured contract.")
            grants = EntitlementFile.model_validate_json(payload)
            if grants.issuer != self.issuer:
                raise ValueError("Entitlement issuer differs from the configured trust root.")
        except (OSError, ValueError, ValidationError) as exc:
            raise IdentityUnavailable("Authorization configuration is unavailable.") from exc
        access = next((entry for entry in grants.bindings if entry.user_id == subject), None)
        if access is None:
            raise IdentityRejected("No active authorization grant exists for this identity.")
        return access


class IdentityVerifier:
    def __init__(self, settings: IdentitySettings, entitlements: EntitlementStore) -> None:
        self.settings, self.entitlements = settings, entitlements
        self.keys = jwt.PyJWKClient(
            settings.jwks_url,
            cache_keys=False,
            lifespan=settings.key_cache_seconds,
            timeout=5,
        )

    async def verify(self, token: str) -> AccessContext:
        return await asyncio.to_thread(self._verify, token)

    def _verify(self, token: str) -> AccessContext:
        if not token or len(token) > 16384:
            raise IdentityRejected("A bounded signed identity token is required.")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != self.settings.algorithm or not isinstance(header.get("kid"), str):
                raise IdentityRejected("The identity token has an unsupported signature contract.")
            if (
                not header["kid"]
                or len(header["kid"]) > 256
                or any(key in header for key in ("jku", "jwk", "x5u", "crit"))
            ):
                raise IdentityRejected("The identity token has an unsupported key contract.")
            signing_key = self.keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=[self.settings.algorithm],
                audience=self.settings.audience,
                issuer=self.settings.issuer,
                leeway=self.settings.leeway_seconds,
                options={"require": ["exp", "iat", "sub", "iss", "aud"], "strict_aud": True},
            )
            if type(claims["iat"]) is not int or type(claims["exp"]) is not int:
                raise IdentityRejected("Identity timestamps must be integer NumericDate claims.")
            if not 0 < claims["exp"] - claims["iat"] <= self.settings.maximum_token_lifetime_seconds:
                raise IdentityRejected("The identity token lifetime exceeds the approved limit.")
            if not isinstance(claims["sub"], str) or not 0 < len(claims["sub"]) <= 256:
                raise IdentityRejected("The identity subject is invalid.")
        except jwt.PyJWKClientConnectionError as exc:
            raise IdentityUnavailable("The identity key service is unavailable.") from exc
        except jwt.PyJWTError as exc:
            raise IdentityRejected("The signed identity token was rejected.") from exc
        # Caller claims such as roles, tenant, regions and clearance never grant authority.
        return self.entitlements.resolve(claims["sub"])
