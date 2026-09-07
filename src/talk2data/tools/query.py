from __future__ import annotations

from talk2data.connectors.base import DataConnector, StructuredQueryPlan
from talk2data.domain.chat import QueryReceipt
from talk2data.domain.models import AccessContext


class ExecuteQueryTool:
    """Executes only a structured plan on an explicitly bound connector."""

    def __init__(self, connector: DataConnector) -> None:
        self._connector = connector

    async def run(self, plan: StructuredQueryPlan, access: AccessContext) -> QueryReceipt:
        return await self._connector.execute_read_only(plan, access)
