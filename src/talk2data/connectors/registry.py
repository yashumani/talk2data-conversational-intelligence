from __future__ import annotations

from talk2data.connectors.base import DataConnector


class ConnectorRegistryError(RuntimeError):
    """Raised for invalid connector registration or lookup."""


class ConnectorRegistry:
    """Runtime registry for governed source adapters."""

    def __init__(self) -> None:
        self._connectors: dict[str, DataConnector] = {}

    def register(self, connector: DataConnector) -> None:
        connector_id = connector.descriptor.connector_id
        if connector_id in self._connectors:
            raise ConnectorRegistryError(f"connector {connector_id!r} is already registered")
        if not connector.descriptor.read_only:
            raise ConnectorRegistryError("Talk2Data connectors must be read-only by default")
        self._connectors[connector_id] = connector

    def get(self, connector_id: str) -> DataConnector:
        try:
            return self._connectors[connector_id]
        except KeyError as exc:
            raise ConnectorRegistryError(f"connector {connector_id!r} is not registered") from exc

    def connectors(self) -> tuple[DataConnector, ...]:
        return tuple(self._connectors.values())

    def descriptors(self) -> list[dict[str, object]]:
        return [connector.descriptor.model_dump(mode="json") for connector in self._connectors.values()]
