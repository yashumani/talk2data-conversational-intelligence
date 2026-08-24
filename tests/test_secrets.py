from __future__ import annotations

import pytest

from talk2data.services.secrets import EnvironmentSecretResolver, SecretResolutionError


def test_environment_secret_resolver_returns_secret_value() -> None:
    resolver = EnvironmentSecretResolver({"T2D_POSTGRES_DSN": "postgresql://user:password@host/database"})

    secret = resolver.resolve("env://T2D_POSTGRES_DSN")

    assert secret.get_secret_value() == "postgresql://user:password@host/database"
    assert str(secret) == "**********"


def test_missing_environment_secret_uses_sanitized_error() -> None:
    resolver = EnvironmentSecretResolver({})

    with pytest.raises(SecretResolutionError) as error:
        resolver.resolve("env://T2D_POSTGRES_DSN")

    assert str(error.value) == "The configured connector secret is unavailable."
    assert "T2D_POSTGRES_DSN" not in str(error.value)


def test_unsupported_secret_provider_is_rejected() -> None:
    resolver = EnvironmentSecretResolver({})

    with pytest.raises(SecretResolutionError) as error:
        resolver.resolve("vault://production/postgres")

    assert str(error.value) == "The connector secret provider is not supported."
