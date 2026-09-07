from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from pydantic import ValidationError

from talk2data.core.internal_config import IdentitySettings, InternalRuntimeConfig
from talk2data.services.identity import (
    EntitlementFile,
    EntitlementStore,
    IdentityRejected,
    IdentityUnavailable,
    IdentityVerifier,
)
from tests.internal_support import access, private_config, write_grants


@pytest.fixture(scope="module")
def signing_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def signed_token(key: Any, **updates: Any) -> str:
    now = int(time.time())
    payload = {
        "sub": "analyst",
        "iss": "https://identity.example.test",
        "aud": "talk2data-internal",
        "iat": now - 5,
        "exp": now + 300,
        **updates,
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture
def verifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signing_key: Any) -> IdentityVerifier:
    config = private_config(tmp_path)
    service = IdentityVerifier(
        config.identity, EntitlementStore(config.entitlements_path, config.identity.issuer)
    )
    monkeypatch.setattr(
        service.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=signing_key.public_key())
    )
    return service


async def test_signed_claims_cannot_grant_roles_or_change_tenant(
    verifier: IdentityVerifier, signing_key: Any
) -> None:
    token = signed_token(signing_key, roles=["TALK2DATA_ADMIN"], tenant_id="other-tenant", regions=["ALL"])
    assert await verifier.verify(token) == access()


@pytest.mark.parametrize(
    "updates",
    [
        {"aud": "other-service"},
        {"aud": ["talk2data-internal"]},
        {"iss": "https://evil.example.test"},
        {"exp": 1},
        {"iat": int(time.time()) + 1000},
        {"nbf": int(time.time()) + 1000},
        {"exp": int(time.time()) + 7200},
        {"sub": ""},
        {"sub": "x" * 257},
        {"sub": 1},
        {"iat": str(int(time.time()))},
        {"exp": str(int(time.time()) + 60)},
        {"exp": False},
        {"iat": False},
        {"iat": int(time.time()) + 10, "exp": int(time.time()) + 5},
    ],
)
async def test_untrusted_claim_contracts_fail(
    verifier: IdentityVerifier, signing_key: Any, updates: dict[str, Any]
) -> None:
    with pytest.raises(IdentityRejected):
        await verifier.verify(signed_token(signing_key, **updates))


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "iss", "aud"])
async def test_required_claims(verifier: IdentityVerifier, signing_key: Any, missing: str) -> None:
    payload = jwt.decode(signed_token(signing_key), options={"verify_signature": False})
    del payload[missing]
    with pytest.raises(IdentityRejected):
        await verifier.verify(
            jwt.encode(payload, signing_key, algorithm="RS256", headers={"kid": "test-key"})
        )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"kid": ""},
        {"kid": "x" * 257},
        {"kid": 1},
        {"kid": "test-key", "jku": "https://evil.example.test"},
        {"kid": "test-key", "crit": ["unsafe"]},
    ],
)
async def test_header_key_controls(
    verifier: IdentityVerifier, signing_key: Any, headers: dict[str, Any]
) -> None:
    with pytest.raises((IdentityRejected, jwt.InvalidTokenError)):
        token = jwt.encode({"sub": "analyst"}, signing_key, algorithm="RS256", headers=headers)
        await verifier.verify(token)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "x" * 16385,
        "broken.jwt.token",
        jwt.encode({"sub": "analyst"}, None, algorithm="none"),
        jwt.encode({"sub": "analyst"}, "x" * 32, algorithm="HS256"),
    ],
)
async def test_invalid_signatures_and_algorithms(verifier: IdentityVerifier, token: str) -> None:
    with pytest.raises(IdentityRejected):
        await verifier.verify(token)


async def test_wrong_signing_key(verifier: IdentityVerifier) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(IdentityRejected):
        await verifier.verify(signed_token(other_key))


async def test_revocation_is_not_hidden_by_a_grant_cache(
    verifier: IdentityVerifier, signing_key: Any
) -> None:
    token = signed_token(signing_key)
    assert await verifier.verify(token) == access()
    write_grants(verifier.entitlements.path)
    with pytest.raises(IdentityRejected):
        await verifier.verify(token)


async def test_key_service_failure(
    verifier: IdentityVerifier, signing_key: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(_: str) -> Any:
        raise jwt.PyJWKClientConnectionError("Private key-service diagnostic must not reach the client")

    monkeypatch.setattr(verifier.keys, "get_signing_key_from_jwt", unavailable)
    with pytest.raises(IdentityUnavailable, match="identity key service"):
        await verifier.verify(signed_token(signing_key))


@pytest.mark.parametrize(
    "payload", [b"bad", b"x" * 1_000_001, b'{"version":"1","issuer":"wrong","bindings":[]}']
)
def test_malformed_grants_fail_closed(verifier: IdentityVerifier, payload: bytes) -> None:
    verifier.entitlements.path.write_bytes(payload)
    with pytest.raises(IdentityUnavailable):
        verifier.entitlements.resolve("analyst")


def test_missing_grants_and_ambiguous_subjects(verifier: IdentityVerifier) -> None:
    verifier.entitlements.path.unlink()
    with pytest.raises(IdentityUnavailable):
        verifier.entitlements.resolve("analyst")
    with pytest.raises(ValidationError, match="unambiguous"):
        EntitlementFile(version="1", issuer="issuer", bindings=[access(), access()])


@pytest.mark.parametrize(
    "url",
    [
        "http://identity.example.test",
        "https://user:secret@identity.example.test",
        "https:///keys",
        "https://identity.example.test?token=secret",
        "https://identity.example.test/#fragment",
    ],
)
def test_identity_configuration_requires_explicit_https(url: str) -> None:
    with pytest.raises(ValidationError):
        IdentitySettings(issuer=url, audience="aud", jwks_url=url)


def test_runtime_configuration_requires_private_absolute_paths(tmp_path: Path) -> None:
    config = private_config(tmp_path)
    path = tmp_path / "runtime.json"
    path.write_text(config.model_dump_json())
    assert InternalRuntimeConfig.load(path) == config
    with pytest.raises(ValidationError):
        InternalRuntimeConfig.model_validate({**config.model_dump(), "entitlements_path": "relative.json"})


async def test_es256_signed_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = private_config(tmp_path)
    identity = config.identity.model_copy(update={"algorithm": "ES256"})
    key = ec.generate_private_key(ec.SECP256R1())
    verifier = IdentityVerifier(identity, EntitlementStore(config.entitlements_path, identity.issuer))
    monkeypatch.setattr(
        verifier.keys, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=key.public_key())
    )
    now = int(time.time())
    token = jwt.encode(
        {"sub": "analyst", "iss": identity.issuer, "aud": identity.audience, "iat": now, "exp": now + 60},
        key,
        algorithm="ES256",
        headers={"kid": "ec-key"},
    )
    assert await verifier.verify(token) == access()
