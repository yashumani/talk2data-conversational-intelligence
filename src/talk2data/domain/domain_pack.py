from __future__ import annotations

from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from talk2data.domain.models import TenantDomainPack


class DomainPackError(RuntimeError):
    """Raised when a Tenant Domain Pack cannot be loaded or resolved."""


class DomainPackNotFoundError(DomainPackError):
    """Raised when no approved pack exists for a tenant."""


class DomainPackRegistry:
    """Loads and exposes approved, versioned Tenant Domain Packs."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory
        self._packs: dict[str, TenantDomainPack] = {}

    def load(self) -> None:
        paths = list(self._iter_pack_paths())
        if not paths:
            raise DomainPackError("no Tenant Domain Pack files were found")

        packs: dict[str, TenantDomainPack] = {}
        for path in paths:
            raw = self._load_yaml(path)
            pack = TenantDomainPack.model_validate(raw)
            if pack.status != "APPROVED":
                continue
            existing = packs.get(pack.tenant_id)
            if existing is not None:
                raise DomainPackError(
                    f"multiple approved Domain Packs found for tenant {pack.tenant_id!r}: "
                    f"{existing.version!r} and {pack.version!r}"
                )
            packs[pack.tenant_id] = pack

        if not packs:
            raise DomainPackError("no approved Tenant Domain Packs were loaded")
        self._packs = packs

    def get(self, tenant_id: str) -> TenantDomainPack:
        try:
            return self._packs[tenant_id]
        except KeyError as exc:
            raise DomainPackNotFoundError(
                f"no approved Tenant Domain Pack exists for tenant {tenant_id!r}"
            ) from exc

    def list_tenants(self) -> list[str]:
        return sorted(self._packs)

    @property
    def loaded(self) -> bool:
        return bool(self._packs)

    def _iter_pack_paths(self) -> Iterable[Path]:
        if self._directory is not None:
            yield from sorted(self._directory.glob("*.yaml"))
            yield from sorted(self._directory.glob("*.yml"))
            return

        packaged = files("talk2data").joinpath("resources", "domain_packs")
        for child in sorted(packaged.iterdir(), key=lambda item: item.name):
            if child.name.endswith((".yaml", ".yml")):
                yield Path(str(child))

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise DomainPackError(f"failed to read Domain Pack {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise DomainPackError(f"Domain Pack {path} must contain a YAML object")
        return raw
