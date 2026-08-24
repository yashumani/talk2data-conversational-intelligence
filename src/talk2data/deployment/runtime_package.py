from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

import yaml

from talk2data.domain.domain_pack import (
    DomainPackNotFoundError,
    DomainPackRegistry,
)
from talk2data.domain.models import TenantDomainPack
from talk2data.domain.onboarding import (
    RuntimePackageMetadata,
    RuntimePackageRequest,
    RuntimePackageValidationResponse,
)
from talk2data.domain.physical_mapping import (
    PhysicalMappingNotFoundError,
    PhysicalMappingRegistry,
    TenantPhysicalMappingPack,
)

RUNTIME_IMAGE = "ghcr.io/yashumani/talk2data-conversational-intelligence:main"
SOURCE_REPOSITORY = "https://github.com/yashumani/talk2data-conversational-intelligence"
_CODESPACES_URL = (
    "https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1"
)
_SECRET_NAME = re.compile(r"^env://([A-Z_][A-Z0-9_]*)$")


class RuntimePackageError(RuntimeError):
    """Raised when a tenant runtime package cannot be created safely."""


@dataclass(frozen=True)
class RuntimePackageArtifact:
    content: bytes
    metadata: RuntimePackageMetadata


@dataclass(frozen=True)
class _ResolvedPackage:
    domain_pack: TenantDomainPack
    mapping_pack: TenantPhysicalMappingPack
    connector_ids: tuple[str, ...]
    warnings: tuple[str, ...]


class RuntimePackageBuilder:
    """Creates deterministic, credential-free tenant deployment bundles."""

    def __init__(
        self,
        *,
        domain_registry: DomainPackRegistry,
        physical_mapping_registry: PhysicalMappingRegistry,
    ) -> None:
        self._domains = domain_registry
        self._mappings = physical_mapping_registry

    def validate(self, request: RuntimePackageRequest) -> RuntimePackageValidationResponse:
        errors: list[str] = []
        warnings: list[str] = []
        resolved: _ResolvedPackage | None = None
        try:
            resolved = self._resolve(request)
        except (RuntimePackageError, PhysicalMappingNotFoundError) as exc:
            errors.append(str(exc))

        file_count = 0
        connector_ids: list[str] = []
        mapping_version: str | None = None
        mapping_hash: str | None = None
        if resolved is not None:
            connector_ids = list(resolved.connector_ids)
            mapping_version = resolved.mapping_pack.version
            mapping_hash = resolved.mapping_pack.canonical_hash()
            warnings.extend(resolved.warnings)
            file_count = len(self._render_files(request, resolved)) + 1

        return RuntimePackageValidationResponse(
            valid=not errors,
            tenant_id=request.access_context.tenant_id,
            project_slug=request.project_slug,
            connector_ids=connector_ids,
            mapping_version=mapping_version,
            mapping_hash=mapping_hash,
            runtime_image=RUNTIME_IMAGE,
            package_file_count=file_count,
            errors=errors,
            warnings=warnings,
        )

    def build(self, request: RuntimePackageRequest) -> RuntimePackageArtifact:
        resolved = self._resolve(request)
        files = self._render_files(request, resolved)
        checksums = {path: hashlib.sha256(content).hexdigest() for path, content in sorted(files.items())}
        files["checksums.json"] = (json.dumps(checksums, indent=2, sort_keys=True) + "\n").encode("utf-8")

        archive = io.BytesIO()
        with zipfile.ZipFile(
            archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as bundle:
            for path, content in sorted(files.items()):
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if path.endswith((".sh", ".ps1")) else 0o644) << 16
                bundle.writestr(info, content)

        content = archive.getvalue()
        digest = hashlib.sha256(content).hexdigest()
        filename = f"{request.project_slug}-talk2data-runtime.zip"
        metadata = RuntimePackageMetadata(
            filename=filename,
            sha256=digest,
            size_bytes=len(content),
            tenant_id=resolved.domain_pack.tenant_id,
            connector_ids=list(resolved.connector_ids),
            mapping_version=resolved.mapping_pack.version,
            mapping_hash=resolved.mapping_pack.canonical_hash(),
            files=sorted(files),
        )
        return RuntimePackageArtifact(content=content, metadata=metadata)

    def _resolve(self, request: RuntimePackageRequest) -> _ResolvedPackage:
        tenant_id = request.access_context.tenant_id
        try:
            domain_pack = self._domains.get(tenant_id)
            mapping_pack = (
                request.physical_mapping_pack
                if request.physical_mapping_pack is not None
                else self._mappings.get(tenant_id)
            )
        except (DomainPackNotFoundError, PhysicalMappingNotFoundError) as exc:
            raise RuntimePackageError(
                "No approved Domain Pack and physical mapping are available for this tenant."
            ) from exc
        if mapping_pack.tenant_id != tenant_id:
            raise RuntimePackageError("The physical mapping tenant does not match the authenticated tenant.")
        if mapping_pack.status != "APPROVED":
            raise RuntimePackageError("Only an APPROVED physical mapping pack can be packaged.")

        failures = _validate_mapping_pack(domain_pack, mapping_pack)
        if failures:
            raise RuntimePackageError("Physical mapping validation failed: " + ", ".join(failures))

        required_connectors = {
            metric.source.connector_id
            for metric in domain_pack.metrics
            if metric.source.status.value == "AVAILABLE"
        }
        available_connectors = {connector.connector_id for connector in mapping_pack.connectors}
        selected = (
            set(request.selected_connector_ids) if request.selected_connector_ids else required_connectors
        )
        unknown = selected - available_connectors
        if unknown:
            raise RuntimePackageError("Unknown connector selection: " + ", ".join(sorted(unknown)))
        missing = required_connectors - selected
        if missing:
            raise RuntimePackageError(
                "The package cannot omit connectors required by available metrics: "
                + ", ".join(sorted(missing))
            )

        selected_pack = mapping_pack.model_copy(
            update={
                "connectors": [
                    connector for connector in mapping_pack.connectors if connector.connector_id in selected
                ]
            }
        )
        warnings: list[str] = []
        if request.physical_mapping_pack is not None:
            warnings.append("A request-supplied physical mapping was validated and embedded.")
        if not request.include_codespaces:
            warnings.append("Codespaces bootstrap files were omitted.")

        return _ResolvedPackage(
            domain_pack=domain_pack,
            mapping_pack=selected_pack,
            connector_ids=tuple(sorted(selected)),
            warnings=tuple(warnings),
        )

    def _render_files(
        self,
        request: RuntimePackageRequest,
        resolved: _ResolvedPackage,
    ) -> dict[str, bytes]:
        tenant = resolved.domain_pack.tenant_id
        secret_names = sorted(
            {_secret_name(connector.secret_ref) for connector in resolved.mapping_pack.connectors}
        )
        files: dict[str, bytes] = {
            "README.md": _readme(request, resolved, secret_names).encode("utf-8"),
            ".env.example": _environment_example(
                request,
                secret_names,
            ).encode("utf-8"),
            "docker-compose.yml": _docker_compose(
                request,
                resolved,
                secret_names,
            ).encode("utf-8"),
            f"config/domain-packs/{tenant}.yaml": _yaml_bytes(resolved.domain_pack.model_dump(mode="json")),
            f"config/physical-mappings/{tenant}.yaml": _yaml_bytes(
                resolved.mapping_pack.model_dump(mode="json")
            ),
            "config/talk2data.yaml": _yaml_bytes(
                {
                    "project_slug": request.project_slug,
                    "display_name": request.display_name,
                    "tenant_id": tenant,
                    "runtime_image": RUNTIME_IMAGE,
                    "ollama_model": request.ollama_model,
                    "api_port": request.api_port,
                    "connectors": list(resolved.connector_ids),
                    "mapping_version": resolved.mapping_pack.version,
                    "mapping_hash": resolved.mapping_pack.canonical_hash(),
                    "source_repository": SOURCE_REPOSITORY,
                }
            ),
            "scripts/start.sh": _start_sh().encode("utf-8"),
            "scripts/start.ps1": _start_ps1().encode("utf-8"),
            ".github/workflows/validate.yml": _validation_workflow(secret_names).encode("utf-8"),
        }
        if request.include_codespaces:
            files[".devcontainer/devcontainer.json"] = _devcontainer().encode("utf-8")
        return files


def _validate_mapping_pack(
    domain_pack: TenantDomainPack,
    mapping_pack: TenantPhysicalMappingPack,
) -> list[str]:
    failures: list[str] = []
    for metric in domain_pack.metrics:
        if metric.source.status.value != "AVAILABLE":
            continue
        try:
            connector = mapping_pack.connector(metric.source.connector_id)
            physical_metric = connector.metric(metric.id)
        except PhysicalMappingNotFoundError:
            failures.append(f"MISSING_PHYSICAL_MAPPING:{metric.id}")
            continue
        if physical_metric.aggregation != metric.aggregation:
            failures.append(f"AGGREGATION_MISMATCH:{metric.id}")
        if physical_metric.allowed_dimensions != set(metric.allowed_dimensions):
            failures.append(f"DIMENSION_MAPPING_MISMATCH:{metric.id}")
    return failures


def _secret_name(secret_ref: str) -> str:
    match = _SECRET_NAME.fullmatch(secret_ref)
    if match is None:
        raise RuntimePackageError("Runtime packages currently support only env:// secret references.")
    return match.group(1)


def _yaml_bytes(value: Any) -> bytes:
    return yaml.safe_dump(
        value,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).encode("utf-8")


def _environment_example(
    request: RuntimePackageRequest,
    secret_names: list[str],
) -> str:
    lines = [
        "# Copy this file to .env and set local values. Never commit .env.",
        f"T2D_PROJECT_SLUG={request.project_slug}",
        f"T2D_API_PORT={request.api_port}",
        f"T2D_RUNTIME_IMAGE={RUNTIME_IMAGE}",
        f"T2D_OLLAMA_MODEL={request.ollama_model}",
        "",
        "# Database credentials are intentionally blank.",
    ]
    lines.extend(f"{name}=" for name in secret_names)
    return "\n".join(lines) + "\n"


def _docker_compose(
    request: RuntimePackageRequest,
    resolved: _ResolvedPackage,
    secret_names: list[str],
) -> str:
    secret_environment = "\n".join(
        f'      {name}: "${{{name}:?Set {name} in .env}}"' for name in secret_names
    )
    if not secret_environment:
        secret_environment = "      # No connector secret references selected."
    tenant = resolved.domain_pack.tenant_id
    return f"""name: ${{T2D_PROJECT_SLUG:-{request.project_slug}}}

services:
  ollama:
    image: ollama/ollama:latest
    restart: unless-stopped
    volumes:
      - ollama_models:/root/.ollama
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 10s
      timeout: 5s
      retries: 30

  ollama-pull:
    image: ollama/ollama:latest
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      OLLAMA_HOST: http://ollama:11434
      T2D_OLLAMA_MODEL: "${{T2D_OLLAMA_MODEL:-{request.ollama_model}}}"
    entrypoint: ["/bin/sh", "-c"]
    command: ["ollama pull $${{T2D_OLLAMA_MODEL}}"]
    restart: "no"

  talk2data:
    image: "${{T2D_RUNTIME_IMAGE:-{RUNTIME_IMAGE}}}"
    pull_policy: always
    depends_on:
      ollama-pull:
        condition: service_completed_successfully
    restart: unless-stopped
    ports:
      - "${{T2D_API_PORT:-{request.api_port}}}:8000"
    environment:
      T2D_ENVIRONMENT: tenant
      T2D_DEFAULT_TENANT_ID: {tenant}
      T2D_DATA_BACKEND: postgresql
      T2D_DATABASE_PATH: /state/talk2data.db
      T2D_DOMAIN_PACK_DIRECTORY: /config/domain-packs
      T2D_PHYSICAL_MAPPING_DIRECTORY: /config/physical-mappings
      T2D_OLLAMA_ENABLED: "true"
      T2D_OLLAMA_REQUIRED: "false"
      T2D_OLLAMA_BASE_URL: http://ollama:11434
      T2D_OLLAMA_MODEL: "${{T2D_OLLAMA_MODEL:-{request.ollama_model}}}"
{secret_environment}
    volumes:
      - ./config:/config:ro
      - talk2data_state:/state
    healthcheck:
      test:
        - CMD-SHELL
        - >-
          python -c "import urllib.request;
          urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"
      interval: 10s
      timeout: 5s
      retries: 30

volumes:
  ollama_models:
  talk2data_state:
"""


def _readme(
    request: RuntimePackageRequest,
    resolved: _ResolvedPackage,
    secret_names: list[str],
) -> str:
    secrets = "\n".join(f"- `{name}`" for name in secret_names) or "- None"
    return f"""# {request.display_name}

This package configures the stable Talk2Data runtime for tenant
`{resolved.domain_pack.tenant_id}`.

## Start

1. Install Docker Desktop or Docker Engine with Compose.
2. Copy `.env.example` to `.env`.
3. Set the required connection secret values in `.env`.
4. Run `docker compose up -d`.
5. Open `http://localhost:{request.api_port}/demo`.
6. Inspect readiness at `http://localhost:{request.api_port}/health/ready`.
7. Inspect the API at `http://localhost:{request.api_port}/docs`.

Required secret variables:

{secrets}

The package contains no database passwords, tokens, or business data. The local
language model interprets questions; governed connectors calculate and verify
all numerical answers.

## Included contracts

- Tenant Domain Pack
- Versioned semantic-to-physical mapping pack
- Docker Compose runtime
- Ollama local-model bootstrap
- GitHub validation workflow
- Reproducible file checksums

Runtime source: {SOURCE_REPOSITORY}

Codespaces evaluation: {_CODESPACES_URL}
"""


def _start_sh() -> str:
    return """#!/usr/bin/env sh
set -eu
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Set the required connector secret values, then run again."
  exit 1
fi
docker compose up -d
docker compose ps
"""


def _start_ps1() -> str:
    return """$ErrorActionPreference = "Stop"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Set the required connector secret values, then run again."
    exit 1
}
docker compose up -d
docker compose ps
"""


def _devcontainer() -> str:
    return """{
  "name": "Talk2Data tenant runtime",
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
  "features": {
    "ghcr.io/devcontainers/features/docker-in-docker:2": {}
  },
  "forwardPorts": [8000],
  "portsAttributes": {
    "8000": {
      "label": "Talk2Data",
      "onAutoForward": "openBrowser"
    }
  },
  "postCreateCommand": "cp -n .env.example .env || true"
}
"""


def _validation_workflow(secret_names: list[str]) -> str:
    placeholders = "\n".join(f"          export {name}=placeholder" for name in secret_names)
    if not placeholders:
        placeholders = "          true"
    return f"""name: Validate Talk2Data tenant package

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  package:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verify package checksums
        run: |
          python - <<'PY'
          import hashlib
          import json
          from pathlib import Path
          expected = json.loads(Path("checksums.json").read_text(encoding="utf-8"))
          actual = {{
              path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
              for path in expected
          }}
          if actual != expected:
              raise SystemExit("Package checksum verification failed.")
          print("Package checksums verified.")
          PY
      - name: Validate Docker Compose
        env:
          T2D_RUNTIME_IMAGE: {RUNTIME_IMAGE}
        run: |
{placeholders}
          docker compose config --quiet
"""
