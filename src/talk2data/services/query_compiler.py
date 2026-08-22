from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from uuid import UUID

from talk2data.domain.models import (
    AccessScope,
    BusinessQueryIR,
    ComparisonSpec,
    ComparisonType,
    CompilationIssue,
    MetricDefinition,
    QueryCompilationRequest,
    QueryCompilationResult,
    QueryCompilationStatus,
    QueryFilter,
    QuestionDecision,
    QuestionIntent,
    QuestionVerdict,
    SourceStatus,
    TenantDomainPack,
    TimeGrain,
    TimePreset,
    TimeWindow,
)
from talk2data.services.interpreter import normalize_text, phrase_present
from talk2data.services.semantic import (
    DimensionNotAllowedError,
    MetricNotFoundError,
    SemanticAccessDeniedError,
    SemanticRegistry,
)

ELIGIBLE_VERDICTS = {
    QuestionVerdict.ACCEPT_INTERNAL,
    QuestionVerdict.ACCEPT_EXTERNAL_AUGMENTED,
}


class BusinessQueryCompiler:
    """Compiles an admissible data question into deterministic Business Query IR."""

    def __init__(self, semantics: SemanticRegistry) -> None:
        self._semantics = semantics

    def compile(
        self,
        *,
        request: QueryCompilationRequest,
        decision: QuestionDecision,
        session_id: UUID,
    ) -> QueryCompilationResult:
        if decision.verdict not in ELIGIBLE_VERDICTS:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.NOT_ELIGIBLE,
                issue=CompilationIssue(
                    code="QUESTION_NOT_ELIGIBLE_FOR_DATA_COMPILATION",
                    message=(
                        "Only questions accepted for internal data or approved external augmentation "
                        "can compile into Business Query IR."
                    ),
                ),
            )

        metric_ids = list(dict.fromkeys(decision.candidate_metric_ids))
        if not metric_ids:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.INVALID,
                issue=CompilationIssue(
                    code="NO_GOVERNED_METRIC",
                    message="The accepted question does not contain a governed metric.",
                    field="metric_id",
                ),
            )
        if len(metric_ids) > 1:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.CLARIFICATION_REQUIRED,
                issue=CompilationIssue(
                    code="MULTIPLE_METRICS_REQUIRE_EXPLICIT_PLAN",
                    message=(
                        "The question refers to multiple governed metrics. Select one primary metric "
                        "or use a later multi-metric investigation plan."
                    ),
                    field="metric_id",
                ),
            )

        try:
            pack, metric = self._semantics.resolve_metric(request.access_context, metric_ids[0])
        except MetricNotFoundError as exc:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.INVALID,
                issue=CompilationIssue(code="METRIC_NOT_FOUND", message=str(exc), field="metric_id"),
            )
        except SemanticAccessDeniedError:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.NOT_ELIGIBLE,
                issue=CompilationIssue(
                    code="SEMANTIC_ACCESS_DENIED",
                    message="The requested metric definition is not available to this user.",
                ),
            )

        if metric.source.status != SourceStatus.AVAILABLE:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.NOT_ELIGIBLE,
                issue=CompilationIssue(
                    code="GOVERNED_SOURCE_NOT_AVAILABLE",
                    message="The metric does not currently have an available governed source.",
                ),
            )

        try:
            dimensions = self._semantics.resolve_dimensions(
                access=request.access_context,
                pack=pack,
                metric=metric,
                dimension_ids=decision.candidate_dimension_ids,
            )
        except DimensionNotAllowedError as exc:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.INVALID,
                issue=CompilationIssue(
                    code="DIMENSION_NOT_ALLOWED_FOR_METRIC",
                    message=str(exc),
                    field="dimensions",
                ),
            )
        except SemanticAccessDeniedError:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.NOT_ELIGIBLE,
                issue=CompilationIssue(
                    code="DIMENSION_ACCESS_DENIED",
                    message="At least one requested dimension is not available to this user.",
                    field="dimensions",
                ),
            )

        time_window, time_warnings, time_issue = self._resolve_time_window(
            request.question,
            metric,
            pack,
            request.as_of.date(),
        )
        if time_issue is not None:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.INVALID,
                issue=time_issue,
            )
        assert time_window is not None

        comparison, comparison_warnings = self._resolve_comparison(
            request.question,
            decision.recognized_intent,
            metric,
        )
        warnings = [*time_warnings, *comparison_warnings]
        semantic_hash = self._semantics.semantic_snapshot_hash(pack, metric)
        access_scope = AccessScope(
            roles=sorted(request.access_context.roles),
            departments=sorted(request.access_context.departments),
            regions=sorted(request.access_context.regions),
            business_units=sorted(request.access_context.business_units),
            permitted_actions=sorted(request.access_context.permitted_actions),
            classification_clearance=request.access_context.classification_clearance,
        )
        dimensions_ids = [entity.id for entity in dimensions]
        filters = self._resolve_filters(request.question, pack, metric)
        try:
            self._semantics.resolve_dimensions(
                access=request.access_context,
                pack=pack,
                metric=metric,
                dimension_ids=[item.dimension_id for item in filters],
            )
        except DimensionNotAllowedError as exc:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.INVALID,
                issue=CompilationIssue(
                    code="FILTER_DIMENSION_NOT_ALLOWED_FOR_METRIC",
                    message=str(exc),
                    field="filters",
                ),
            )
        except SemanticAccessDeniedError:
            return self._outcome(
                session_id=session_id,
                decision=decision,
                status=QueryCompilationStatus.NOT_ELIGIBLE,
                issue=CompilationIssue(
                    code="FILTER_DIMENSION_ACCESS_DENIED",
                    message="A detected filter dimension is not available to this user.",
                    field="filters",
                ),
            )
        plan_hash = self._plan_hash(
            request=request,
            metric=metric,
            pack=pack,
            dimensions=dimensions_ids,
            filters=filters,
            time_window=time_window,
            comparison=comparison,
            access_scope=access_scope,
            semantic_hash=semantic_hash,
            requires_external_context=(decision.verdict == QuestionVerdict.ACCEPT_EXTERNAL_AUGMENTED),
        )
        query_ir = BusinessQueryIR(
            session_id=session_id,
            decision_id=decision.decision_id,
            tenant_id=request.access_context.tenant_id,
            user_id=request.access_context.user_id,
            question=request.question,
            recognized_intent=decision.recognized_intent,
            metric_id=metric.id,
            metric_name=metric.name,
            semantic_version=metric.semantic_version,
            value_type=metric.value_type,
            aggregation=metric.aggregation,
            additivity=metric.additivity,
            unit=metric.unit,
            currency=pack.default_currency if metric.value_type.value == "CURRENCY" else None,
            dimensions=dimensions_ids,
            filters=filters,
            time_window=time_window,
            comparison=comparison,
            access_scope=access_scope,
            source_connector_id=metric.source.connector_id,
            domain_pack_version=pack.version,
            semantic_snapshot_hash=semantic_hash,
            plan_hash=plan_hash,
            requires_external_context=(decision.verdict == QuestionVerdict.ACCEPT_EXTERNAL_AUGMENTED),
            warnings=warnings,
        )
        return QueryCompilationResult(
            session_id=session_id,
            decision=decision,
            status=QueryCompilationStatus.COMPILED,
            query_ir=query_ir,
            warnings=warnings,
        )

    @staticmethod
    def _outcome(
        *,
        session_id: UUID,
        decision: QuestionDecision,
        status: QueryCompilationStatus,
        issue: CompilationIssue,
    ) -> QueryCompilationResult:
        return QueryCompilationResult(
            session_id=session_id,
            decision=decision,
            status=status,
            issues=[issue],
        )

    @staticmethod
    def _resolve_time_window(
        question: str,
        metric: MetricDefinition,
        pack: TenantDomainPack,
        anchor_date: date,
    ) -> tuple[TimeWindow | None, list[str], CompilationIssue | None]:
        normalized = normalize_text(question)
        iso_dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", normalized)
        if len(iso_dates) > 2:
            return (
                None,
                [],
                CompilationIssue(
                    code="TOO_MANY_EXPLICIT_DATES",
                    message="The question contains more than two explicit dates.",
                    field="time_window",
                ),
            )
        if len(iso_dates) == 2:
            try:
                start_date = date.fromisoformat(iso_dates[0])
                end_date = date.fromisoformat(iso_dates[1])
            except ValueError:
                return (
                    None,
                    [],
                    CompilationIssue(
                        code="INVALID_EXPLICIT_DATE",
                        message="At least one explicit date is not a valid calendar date.",
                        field="time_window",
                    ),
                )
            if start_date > end_date:
                return (
                    None,
                    [],
                    CompilationIssue(
                        code="INVALID_DATE_RANGE",
                        message="The requested start date occurs after the end date.",
                        field="time_window",
                    ),
                )
            return (
                TimeWindow(
                    preset=TimePreset.CUSTOM,
                    grain=metric.default_time_grain,
                    calendar=pack.default_calendar,
                    timezone=pack.default_timezone,
                    anchor_date=anchor_date,
                    start_date=start_date,
                    end_date=end_date,
                ),
                [],
                None,
            )
        if len(iso_dates) == 1:
            if " on " not in f" {normalized} ":
                return (
                    None,
                    [],
                    CompilationIssue(
                        code="UNSUPPORTED_OPEN_ENDED_DATE_RANGE",
                        message=(
                            "A single explicit date must be used with 'on'. Open-ended ranges require "
                            "an explicit start and end date."
                        ),
                        field="time_window",
                    ),
                )
            try:
                selected_date = date.fromisoformat(iso_dates[0])
            except ValueError:
                return (
                    None,
                    [],
                    CompilationIssue(
                        code="INVALID_EXPLICIT_DATE",
                        message="The explicit date is not a valid calendar date.",
                        field="time_window",
                    ),
                )
            return (
                TimeWindow(
                    preset=TimePreset.CUSTOM,
                    grain=TimeGrain.DAY,
                    calendar=pack.default_calendar,
                    timezone=pack.default_timezone,
                    anchor_date=anchor_date,
                    start_date=selected_date,
                    end_date=selected_date,
                ),
                [],
                None,
            )

        patterns: tuple[tuple[tuple[str, ...], TimePreset, TimeGrain], ...] = (
            (("today", "current day"), TimePreset.CURRENT_DAY, TimeGrain.DAY),
            (("yesterday", "previous day"), TimePreset.PREVIOUS_COMPLETE_DAY, TimeGrain.DAY),
            (("this week", "current week"), TimePreset.CURRENT_WEEK, TimeGrain.WEEK),
            (("last week", "previous week"), TimePreset.PREVIOUS_COMPLETE_WEEK, TimeGrain.WEEK),
            (("this month", "current month"), TimePreset.CURRENT_MONTH, TimeGrain.MONTH),
            (("last month", "previous month"), TimePreset.PREVIOUS_COMPLETE_MONTH, TimeGrain.MONTH),
            (("this quarter", "current quarter"), TimePreset.CURRENT_QUARTER, TimeGrain.QUARTER),
            (
                ("last quarter", "previous quarter"),
                TimePreset.PREVIOUS_COMPLETE_QUARTER,
                TimeGrain.QUARTER,
            ),
            (("this year", "current year"), TimePreset.CURRENT_YEAR, TimeGrain.YEAR),
            (("last year", "previous year"), TimePreset.PREVIOUS_COMPLETE_YEAR, TimeGrain.YEAR),
            (("last 30 days", "past 30 days"), TimePreset.ROLLING_30_DAYS, TimeGrain.DAY),
            (("last 12 months", "past 12 months"), TimePreset.ROLLING_12_MONTHS, TimeGrain.MONTH),
        )
        for phrases, preset, grain in patterns:
            if any(phrase in normalized for phrase in phrases):
                if grain not in metric.supported_time_grains:
                    return (
                        None,
                        [],
                        CompilationIssue(
                            code="TIME_GRAIN_NOT_SUPPORTED",
                            message=(
                                f"Metric {metric.id!r} does not support the requested {grain.value} grain."
                            ),
                            field="time_window.grain",
                        ),
                    )
                return (
                    TimeWindow(
                        preset=preset,
                        grain=grain,
                        calendar=pack.default_calendar,
                        timezone=pack.default_timezone,
                        anchor_date=anchor_date,
                    ),
                    [],
                    None,
                )

        return (
            TimeWindow(
                preset=metric.default_time_window,
                grain=metric.default_time_grain,
                calendar=pack.default_calendar,
                timezone=pack.default_timezone,
                anchor_date=anchor_date,
            ),
            ["DEFAULT_TIME_WINDOW_APPLIED"],
            None,
        )

    @staticmethod
    def _resolve_filters(
        question: str,
        pack: TenantDomainPack,
        metric: MetricDefinition,
    ) -> list[QueryFilter]:
        normalized = normalize_text(question)
        filters: list[QueryFilter] = []
        entity_map = {entity.id: entity for entity in pack.entities}
        for dimension_id in metric.allowed_dimensions:
            entity = entity_map[dimension_id]
            matched_values = [
                value.id
                for value in entity.values
                if any(
                    phrase_present(normalized, phrase)
                    for phrase in (value.name, value.id.replace("_", " "), *value.aliases)
                )
            ]
            if matched_values:
                filters.append(
                    QueryFilter(
                        dimension_id=dimension_id,
                        values=list(dict.fromkeys(matched_values)),
                    )
                )
        return filters

    @staticmethod
    def _resolve_comparison(
        question: str,
        intent: QuestionIntent,
        metric: MetricDefinition,
    ) -> tuple[ComparisonSpec, list[str]]:
        normalized = normalize_text(question)
        if any(
            phrase in normalized
            for phrase in ("year over year", "year-over-year", "yoy", "same period last year")
        ):
            return ComparisonSpec(comparison_type=ComparisonType.YEAR_OVER_YEAR), []
        if any(
            phrase in normalized
            for phrase in (
                "previous period",
                "prior period",
                "compared to last",
                "compared with last",
                "compared to previous",
                "compared with previous",
                "versus last",
                "versus previous",
                "vs last",
                "vs previous",
            )
        ):
            return ComparisonSpec(comparison_type=ComparisonType.PRIOR_PERIOD), []
        if intent == QuestionIntent.COMPARISON and metric.default_comparison != ComparisonType.NONE:
            return (
                ComparisonSpec(comparison_type=metric.default_comparison),
                ["DEFAULT_COMPARISON_APPLIED"],
            )
        return ComparisonSpec(), []

    @staticmethod
    def _plan_hash(
        *,
        request: QueryCompilationRequest,
        metric: MetricDefinition,
        pack: TenantDomainPack,
        dimensions: list[str],
        filters: list[QueryFilter],
        time_window: TimeWindow,
        comparison: ComparisonSpec,
        access_scope: AccessScope,
        semantic_hash: str,
        requires_external_context: bool,
    ) -> str:
        payload = {
            "tenant_id": request.access_context.tenant_id,
            "user_id": request.access_context.user_id,
            "metric_id": metric.id,
            "semantic_version": metric.semantic_version,
            "dimensions": dimensions,
            "filters": [item.model_dump(mode="json") for item in filters],
            "time_window": time_window.model_dump(mode="json"),
            "comparison": comparison.model_dump(mode="json"),
            "access_scope": access_scope.model_dump(mode="json"),
            "source_connector_id": metric.source.connector_id,
            "currency": pack.default_currency if metric.value_type.value == "CURRENCY" else None,
            "domain_pack_version": pack.version,
            "semantic_snapshot_hash": semantic_hash,
            "requires_external_context": requires_external_context,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
