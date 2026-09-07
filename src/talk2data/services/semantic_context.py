"""Attach exact business definitions to a governed answer without replacing execution evidence."""

from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.governance import DefinitionSnapshot, SemanticCitation


def cite_definitions(response: DemoChatResponse, snapshot: DefinitionSnapshot) -> DemoChatResponse:
    ir = response.query_ir
    if ir is not None:
        metric = next(m for m in snapshot.pack.metrics if m.id == ir.metric_id)
        dimension_ids = set(ir.dimensions) | {item.dimension_id for item in ir.filters}
        response.semantic_context = SemanticCitation(
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_id,
            publication_sequence=snapshot.sequence,
            effective_from=snapshot.pack.effective_from,
            metric=metric.model_copy(deep=True),
            dimensions=[d.model_copy(deep=True) for d in snapshot.pack.entities if d.id in dimension_ids],
        )
        if response.receipt is not None:
            response.receipt.definition_snapshot_id = snapshot.snapshot_id
    return response
