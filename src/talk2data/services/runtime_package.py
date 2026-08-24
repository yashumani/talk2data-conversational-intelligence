from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

import yaml

from talk2data.domain.models import MetricDefinition, SourceStatus
from talk2data.domain.physical_mapping import PhysicalMappingNotFoundError
from talk2data.domain.runtime_package import (
    RuntimePackageFile,
    RuntimePackagePreview,
    RuntimePackageRequest,
)

RUNTIME_IMAGE = "ghcr.io/yashumani/talk2data-conversational-intelligence:edge"
_FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


class RuntimePackageValidationError(RuntimeError):
    """Raised when a tenant runtime package would be unsafe or incomplete."""


@dataclass(frozen=True)
class RuntimePackageArtifact:
    preview: RuntimePackagePreview
    archive: bytes
    filename: str


class RuntimePackageBuilder:
    """Creates a deterministic, credential-free Talk2Data deployment package."""

    def build(self, request: RuntimePackageRequest) -> RuntimePackageArtifact:
        self._require_admin(request)
        self._validate_semantic_mapping(request)

        base_files = self._render_base_files(request)
        package_id = self._package_id(request, base_files)
        manifest = self._manifest(request, package_id, base_files)
        files = {**base_files, "manifest.json": _json_bytes(manifest)}
        preview = RuntimePackagePreview(
            package_id=package_id,
            project_slug=request.project_slug,
            runtime_image=RUNTIME_IMAGE,
            files=[self._file_record(path, content) for path, content in sorted(files.items())],
            warnings=[
                "The package contains source object and column names; keep it private when those names are proprietary.",
                "Database credentials are not included. Populate only the generated environment variables at runtime.",
            ],
        )
        return RuntimePackageArtifact(
            preview=preview,
            archive=self._zip(files),
            filename=f"{request.project_slug}-talk2data-runtime.zip",
        )

    @staticmethod
    def _require_admin(request: RuntimePackageRequest) -> None:
        if "TALK2DATA_ADMIN" not in request.access_context.roles:
            raise RuntimePackageValidationError(
                "Talk2Data administrator access is required to generate a runtime package."
            )

    @staticmethod
    def _validate_semantic_mapping(request: RuntimePackageRequest) -> None:
        mapping_pack = request.physical_mapping_pack
        domain_pack = request.domain_pack
        semantic_metric_ids: set[str] = set()

        for metric in domain_pack.metrics:
            if metric.source.status != SourceStatus.AVAILABLE:
                continue
            semantic_metric_ids.add(metric.id)
            try:
                connector = mapping_pack.connector(metric.source.connector_id)
                physical = connector.metric(metric.id)
            except PhysicalMappingNotFoundError as exc:
                raise RuntimePackageValidationError(
                    f"No approved physical mapping exists for metric {metric.id!r}."
                ) from exc
            RuntimePackageBuilder._validate_metric(metric, physical.aggregation, physical.allowed_dimensions)

        physical_metric_ids = {
            metric.metric_id for connector in mapping_pack.connectors for metric in connector.metrics
        }
        unknown_metrics = physical_metric_ids - semantic_metric_ids
        if unknown_metrics:
            raise RuntimePackageValidationError(
                "Physical mappings contain metrics absent from the approved Domain Pack: "
                + ", ".join(sorted(unknown_metrics))
            )

    @staticmethod
    def _validate_metric(
        metric: MetricDefinition,
        physical_aggregation: Any,
        physical_dimensions: set[str],
    ) -> None:
        if physical_aggregation != metric.aggregation:
            raise RuntimePackageValidationError(f"Aggregation mismatch for metric {metric.id!r}.")
        if physical_dimensions != set(metric.allowed_dimensions):
            raise RuntimePackageValidationError(f"Dimension mapping mismatch for metric {metric.id!r}.")

    def _render_base_files(self, request: RuntimePackageRequest) -> dict[str, bytes]:
        secret_names = self._secret_names(request)
        return {
            "talk2data.yaml": _yaml_bytes(self._talk2data_config(request)),
            "config/domain-packs/domain-pack.yaml": _yaml_bytes(request.domain_pack),
            "config/physical-mappings/physical-mapping.yaml": _yaml_bytes(request.physical_mapping_pack),
            "config/policies/policies.yaml": _yaml_bytes(self._policy_config(request)),
            "config/harness/harness.yaml": _yaml_bytes(self._harness_config(request)),
            "docker-compose.yml": _yaml_bytes(self._compose_config(request, secret_names)),
            ".env.example": self._environment_example(request, secret_names).encode("utf-8"),
            "README.md": self._readme(request, secret_names).encode("utf-8"),
        }

    @staticmethod
    def _talk2data_config(request: RuntimePackageRequest) -> dict[str, Any]:
        return {
            "api_version": "talk2data/v1",
            "project": {
                "name": request.project_name,
                "slug": request.project_slug,
                "tenant_id": request.domain_pack.tenant_id,
            },
            "runtime": {
                "image": RUNTIME_IMAGE,
                "api_port": request.api_port,
                "data_backend": "POSTGRESQL",
            },
            "model": {
                "provider": request.model.provider.value,
                "model_id": request.model.model_id,
                "timeout_seconds": request.model.timeout_seconds,
                "responsibility": "QUESTION_INTERPRETATION_ONLY",
            },
            "governance": {
                "domain_pack_version": request.domain_pack.version,
                "physical_mapping_version": request.physical_mapping_pack.version,
                "physical_mapping_hash": request.physical_mapping_pack.canonical_hash(),
                "numeric_claims_require_receipts": True,
                "unsupported_answers_abstain": True,
            },
        }

    @staticmethod
    def _policy_config(request: RuntimePackageRequest) -> dict[str, Any]:
        connectors = [connector.connector_id for connector in request.physical_mapping_pack.connectors]
        return {
            "api_version": "talk2data/policy/v1",
            "tenant_id": request.domain_pack.tenant_id,
            "defaults": {
                "data_access": "DENY",
                "connector_access": "DENY",
                "minimum_numeric_claim_status": "VERIFIED",
            },
            "required_runtime_controls": [
                "READ_ONLY_CONNECTORS",
                "PARAMETERIZED_VALUES",
                "POLICY_SCOPE_PUSHDOWN",
                "SOURCE_COVERAGE_CHECK",
                "RESULT_HASH",
                "QUERY_RECEIPT",
            ],
            "configured_connectors": sorted(connectors),
        }

    @staticmethod
    def _harness_config(request: RuntimePackageRequest) -> dict[str, Any]:
        return {
            "api_version": "harnesslab/v1",
            "name": f"{request.project_slug}-talk2data-harness",
            "mode": "GOVERNED_TALK2DATA",
            "stages": [
                "QUESTION_ADMISSIBILITY",
                "SEMANTIC_RESOLUTION",
                "AUTHORIZATION",
                "BUSINESS_QUERY_IR",
                "READ_ONLY_EXECUTION",
                "RESULT_SENSE_VALIDATION",
                "CLAIM_CERTIFICATION",
                "RESPONSE_COMPOSITION",
            ],
            "model_permissions": {
                "interpret_language": True,
                "define_metrics": False,
                "generate_executed_sql": False,
                "authorize_data": False,
                "calculate_certified_values": False,
            },
            "stop_conditions": [
                "AMBIGUOUS_METRIC",
                "UNAUTHORIZED",
                "SOURCE_NOT_READY",
                "VERIFICATION_FAILED",
                "CONTEXT_NOT_CONNECTED",
            ],
        }

    @staticmethod
    def _compose_config(
        request: RuntimePackageRequest,
        secret_names: list[str],
    ) -> dict[str, Any]:
        api_environment: dict[str, str] = {
            "T2D_ENVIRONMENT": "production",
            "T2D_DEFAULT_TENANT_ID": request.domain_pack.tenant_id,
            "T2D_DATABASE_PATH": "/app/.talk2data/talk2data.db",
            "T2D_DOMAIN_PACK_DIRECTORY": "/app/config/domain-packs",
            "T2D_PHYSICAL_MAPPING_DIRECTORY": "/app/config/physical-mappings",
            "T2D_DATA_BACKEND": "POSTGRESQL",
            "T2D_OLLAMA_ENABLED": "true",
            "T2D_OLLAMA_REQUIRED": "true",
            "T2D_OLLAMA_BASE_URL": "http://ollama:11434",
            "T2D_OLLAMA_MODEL": request.model.model_id,
            "T2D_OLLAMA_TIMEOUT_SECONDS": str(request.model.timeout_seconds),
            "T2D_HERMES_ENABLED": "false",
        }
        for secret_name in secret_names:
            api_environment[secret_name] = f"${{{secret_name}:?Set {secret_name}}}"

        return {
            "name": request.project_slug,
            "services": {
                "ollama": {
                    "image": "ollama/ollama:latest",
                    "volumes": ["ollama-data:/root/.ollama"],
                    "healthcheck": {
                        "test": ["CMD", "ollama", "list"],
                        "interval": "10s",
                        "timeout": "5s",
                        "retries": 18,
                    },
                },
                "ollama-model": {
                    "image": "ollama/ollama:latest",
                    "environment": {
                        "OLLAMA_HOST": "http://ollama:11434",
                        "T2D_OLLAMA_MODEL": request.model.model_id,
                    },
                    "entrypoint": ["/bin/sh", "-c"],
                    "command": ["ollama pull $${T2D_OLLAMA_MODEL}"],
                    "depends_on": {"ollama": {"condition": "service_healthy"}},
                },
                "api": {
                    "image": RUNTIME_IMAGE,
                    "ports": [f"{request.api_port}:8000"],
                    "environment": api_environment,
                    "volumes": [
                        "./config/domain-packs:/app/config/domain-packs:ro",
                        "./config/physical-mappings:/app/config/physical-mappings:ro",
                        "talk2data-state:/app/.talk2data",
                    ],
                    "depends_on": {"ollama-model": {"condition": "service_completed_successfully"}},
                    "healthcheck": {
                        "test": [
                            "CMD",
                            "python",
                            "-c",
                            (
                                "import urllib.request; "
                                "urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5)"
                            ),
                        ],
                        "interval": "15s",
                        "timeout": "8s",
                        "retries": 20,
                    },
                },
            },
            "volumes": {"ollama-data": {}, "talk2data-state": {}},
        }

    @staticmethod
    def _environment_example(
        request: RuntimePackageRequest,
        secret_names: list[str],
    ) -> str:
        lines = [
            f"# {request.project_name}",
            "# Copy to .env and set values locally. Never commit .env.",
            f"T2D_OLLAMA_MODEL={request.model.model_id}",
        ]
        for secret_name in secret_names:
            lines.append(f"{secret_name}=postgresql://readonly_user:replace-me@database:5432/analytics")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _readme(request: RuntimePackageRequest, secret_names: list[str]) -> str:
        secret_checklist = "\n".join(f"- `{name}`" for name in secret_names)
        return f"""# {request.project_name}

This package runs Talk2Data with a local Ollama model and approved PostgreSQL physical mappings.
It contains no database credentials and no production data.

## Start

1. Install Docker Desktop or Docker Engine with Compose.
2. Copy `.env.example` to `.env`.
3. Replace every placeholder connection string with a read-only PostgreSQL credential.
4. Run `docker compose up -d`.
5. Open `http://localhost:{request.api_port}/demo`.
6. Inspect the API at `http://localhost:{request.api_port}/docs`.

## Required environment variables

{secret_checklist}

## Accuracy boundary

- Ollama interprets language only.
- The Domain Pack defines business meaning.
- The physical mapping pack defines approved database objects and columns.
- Talk2Data compiles parameterized, read-only queries.
- Every released number must pass verification and carry a query receipt.
- Unsupported, ambiguous, unauthorized, stale, or unverifiable requests abstain.

## Security

Keep this repository private when schema or column names are proprietary. Do not commit `.env`,
credentials, customer data, employee data, or organizational memory. Use a dedicated database role
with read-only access to approved views.
"""

    @staticmethod
    def _secret_names(request: RuntimePackageRequest) -> list[str]:
        names = {
            connector.secret_ref.split("://", 1)[1] for connector in request.physical_mapping_pack.connectors
        }
        return sorted(names)

    @staticmethod
    def _package_id(request: RuntimePackageRequest, files: dict[str, bytes]) -> str:
        payload = {
            "project_slug": request.project_slug,
            "tenant_id": request.domain_pack.tenant_id,
            "domain_pack_version": request.domain_pack.version,
            "physical_mapping_hash": request.physical_mapping_pack.canonical_hash(),
            "runtime_image": RUNTIME_IMAGE,
            "model": request.model.model_dump(mode="json"),
            "files": {path: hashlib.sha256(content).hexdigest() for path, content in sorted(files.items())},
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _manifest(
        request: RuntimePackageRequest,
        package_id: str,
        files: dict[str, bytes],
    ) -> dict[str, Any]:
        return {
            "api_version": "talk2data/package/v1",
            "package_id": package_id,
            "project_slug": request.project_slug,
            "tenant_id": request.domain_pack.tenant_id,
            "runtime_image": RUNTIME_IMAGE,
            "domain_pack_version": request.domain_pack.version,
            "physical_mapping_version": request.physical_mapping_pack.version,
            "physical_mapping_hash": request.physical_mapping_pack.canonical_hash(),
            "files": [
                {
                    "path": path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
                for path, content in sorted(files.items())
            ],
        }

    @staticmethod
    def _file_record(path: str, content: bytes) -> RuntimePackageFile:
        return RuntimePackageFile(
            path=path,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    @staticmethod
    def _zip(files: dict[str, bytes]) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path, content in sorted(files.items()):
                info = zipfile.ZipInfo(path, date_time=_FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
        return stream.getvalue()


def _yaml_bytes(value: Any) -> bytes:
    return yaml.safe_dump(
        _canonicalize(value),
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
    ).encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(_canonicalize(value), sort_keys=True, indent=2) + "\n").encode("utf-8")


def _canonicalize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _canonicalize(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        return sorted(_canonicalize(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
