from __future__ import annotations

from talk2data.domain.models import AccessContext, MetricResolutionResponse
from talk2data.services.semantic import SemanticRegistry


class ResolveMetricTool:
    """Returns the approved definition and version/hash, never an invented definition."""

    def __init__(self, semantics: SemanticRegistry) -> None:
        self._semantics = semantics

    def run(self, access: AccessContext, metric_id: str) -> MetricResolutionResponse:
        return self._semantics.resolve_metric_response(access, metric_id)
