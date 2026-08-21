from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import gradio as gr

from talk2data.connectors.demo_sqlite import DemoSQLiteConnector
from talk2data.connectors.registry import ConnectorRegistry
from talk2data.domain.chat import DemoChatRequest, DemoChatResponse
from talk2data.domain.domain_pack import DomainPackRegistry
from talk2data.domain.models import AccessContext
from talk2data.services.admissibility import QuestionAdmissibilityEngine
from talk2data.services.demo_chat import DemoChatService
from talk2data.services.interpreter import (
    CompositeQuestionInterpreter,
    HeuristicQuestionInterpreter,
    OllamaQuestionInterpreter,
)
from talk2data.services.policy import PolicyEngine
from talk2data.services.query_compiler import BusinessQueryCompiler
from talk2data.services.semantic import SemanticRegistry
from talk2data.services.session_store import SQLiteSessionStore
from talk2data.services.transformers_interpreter import (
    TransformersConfiguration,
    TransformersQuestionInterpreter,
)

MODEL_ID = os.getenv("T2D_HF_MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct")
MODEL_DEVICE = os.getenv("T2D_HF_DEVICE", "auto")
MODEL_REQUIRED = os.getenv("T2D_HF_MODEL_REQUIRED", "false").casefold() == "true"
STATE_DIRECTORY = Path(os.getenv("T2D_STATE_DIRECTORY", "/tmp/talk2data"))
DEMO_AS_OF = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)

EXAMPLE_QUESTIONS = [
    "What was postpaid churn by plan last month?",
    "Compare mobile activations in Northeast last month to the previous period.",
    "What were mobile activations this month?",
    "What was ARPA last month?",
    "What is our restaurant food-cost margin by location?",
    "Did food-delivery application traffic contribute to network congestion?",
]

DEMO_ACCESS = AccessContext(
    tenant_id="demo-telecom",
    user_id="huggingface-demo-user",
    roles={"TALK2DATA_ADMIN"},
    departments={"BUSINESS_INTELLIGENCE"},
    regions={"NORTH_AMERICA"},
    business_units={"CONSUMER"},
    classification_clearance="RESTRICTED",
    permitted_actions={
        "ASK_BUSINESS_QUESTIONS",
        "READ_AGGREGATED_DATA",
        "USE_EXTERNAL_CONTEXT",
    },
)


class HostedDemoRuntime:
    def __init__(self) -> None:
        self._initialization_lock = asyncio.Lock()
        self._initialized = False
        STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)

        domain_registry = DomainPackRegistry()
        domain_registry.load()
        model_interpreter = TransformersQuestionInterpreter(
            TransformersConfiguration(
                model_id=MODEL_ID,
                device=MODEL_DEVICE,
                cache_dir=Path(os.getenv("HF_HOME", "/tmp/huggingface-cache")),
            )
        )
        interpreter = CompositeQuestionInterpreter(
            HeuristicQuestionInterpreter(),
            cast(OllamaQuestionInterpreter, model_interpreter),
            ollama_required=MODEL_REQUIRED,
        )
        policy_engine = PolicyEngine()
        admissibility_engine = QuestionAdmissibilityEngine(interpreter, policy_engine)
        semantic_registry = SemanticRegistry(domain_registry, policy_engine)
        query_compiler = BusinessQueryCompiler(semantic_registry)
        session_store = SQLiteSessionStore(STATE_DIRECTORY / "sessions.db")

        connectors = [
            DemoSQLiteConnector(
                connector_id="telecom_semantic_warehouse",
                database_path=STATE_DIRECTORY / "demo-telecom.db",
                allowed_metric_ids={"POSTPAID_CHURN", "MOBILE_ACTIVATIONS"},
            ),
            DemoSQLiteConnector(
                connector_id="network_performance_platform",
                database_path=STATE_DIRECTORY / "demo-telecom.db",
                allowed_metric_ids={"NETWORK_CONGESTION"},
            ),
        ]
        connector_registry = ConnectorRegistry()
        for connector in connectors:
            connector_registry.register(connector)

        self._model_interpreter = model_interpreter
        self._session_store = session_store
        self._connectors = connectors
        self.service = DemoChatService(
            domain_registry=domain_registry,
            admissibility_engine=admissibility_engine,
            query_compiler=query_compiler,
            session_store=session_store,
            connector_registry=connector_registry,
            ai_model=f"{MODEL_ID} via Transformers",
        )

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialization_lock:
            if self._initialized:
                return
            await self._session_store.initialize()
            for connector in self._connectors:
                await connector.initialize()
            self._initialized = True

    async def model_status(self) -> str:
        ready, detail = await self._model_interpreter.health()
        return ("Ready: " if ready else "Unavailable: ") + detail


runtime = HostedDemoRuntime()


def _history_with_message(
    history: list[dict[str, str]] | None,
    role: str,
    content: str,
) -> list[dict[str, str]]:
    result = list(history or [])
    result.append({"role": role, "content": content})
    return result


def _display_mode(response: DemoChatResponse) -> str:
    value = response.decision.interpreter_mode.value
    return value.replace("OLLAMA", "LOCAL_MODEL")


def _claims_markdown(response: DemoChatResponse) -> str:
    if response.answer is None or not response.answer.claims:
        return "No numeric claim was released."
    return "\n\n".join(f"- {claim.statement}" for claim in response.answer.claims)


def _json_or_empty(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return cast(dict[str, Any], value.model_dump(mode="json"))
    return cast(dict[str, Any], value)


async def ask_question(
    question: str,
    history: list[dict[str, str]] | None,
    session_id: str | None,
) -> tuple[
    list[dict[str, str]],
    str,
    str,
    str,
    str,
    str,
    dict[str, Any],
    dict[str, Any],
    str,
]:
    normalized = " ".join(question.split())
    if not normalized:
        return (
            history or [],
            "",
            session_id or "",
            "No request",
            "No decision",
            "No numeric claim was released.",
            {},
            {},
            "Enter a business question.",
        )

    await runtime.initialize()
    updated_history = _history_with_message(history, "user", normalized)
    try:
        request = DemoChatRequest(
            question=normalized,
            access_context=DEMO_ACCESS,
            session_id=None if not session_id else UUID(session_id),
            use_llm=True,
            include_debug=True,
            as_of=DEMO_AS_OF,
        )
        response = await runtime.service.answer(request)
    except Exception as exc:  # Gradio boundary: present a safe diagnostic, not a traceback
        updated_history = _history_with_message(
            updated_history,
            "assistant",
            "The hosted demonstration could not complete this request. Please retry after the "
            "model finishes loading.",
        )
        return (
            updated_history,
            "",
            session_id or "",
            "Runtime error",
            "No certified decision",
            "No numeric claim was released.",
            {},
            {},
            f"Runtime diagnostic: {type(exc).__name__}: {exc}",
        )

    updated_history = _history_with_message(updated_history, "assistant", response.message)
    warnings = [*response.warnings, *response.decision.warnings]
    model_status = await runtime.model_status()
    return (
        updated_history,
        "",
        str(response.session_id),
        f"{_display_mode(response)} · {response.ai_model or 'deterministic rules'}",
        f"{response.status.value} · {response.decision.verdict.value}",
        _claims_markdown(response),
        _json_or_empty(response.receipt),
        _json_or_empty(response.query_ir),
        model_status + ("\n\nWarnings: " + "; ".join(warnings) if warnings else ""),
    )


with gr.Blocks(
    title="Talk2Data Conversational Intelligence",
    theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="lime"),
    css="""
    .t2d-title h1 { font-size: clamp(2.2rem, 6vw, 4.8rem); letter-spacing: -.05em; }
    .t2d-boundary { border: 1px solid var(--border-color-primary); border-radius: 14px; padding: 12px; }
    """,
) as demo:
    session_state = gr.State("")
    gr.Markdown(
        """
        # Talk2Data
        **Governed local-model interpretation with deterministic, receipt-backed answers.**

        This public Space uses synthetic telecom data. The Unified AI Brain context service is
        intentionally separate. The model interprets language only; it does not calculate or
        certify any number.
        """,
        elem_classes=["t2d-title"],
    )
    gr.Markdown(
        "Model loads on the first request. Free hardware may sleep, so the first response can take longer.",
        elem_classes=["t2d-boundary"],
    )

    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                value=[
                    {
                        "role": "assistant",
                        "content": (
                            "Ask a telecom business question. I will return a verified answer, "
                            "request clarification, or abstain."
                        ),
                    }
                ],
                type="messages",
                height=500,
                label="Conversation",
            )
            question_box = gr.Textbox(
                label="Business question",
                placeholder="What was postpaid churn by plan last month?",
                lines=2,
            )
            with gr.Row():
                ask_button = gr.Button("Ask", variant="primary")
                clear_button = gr.ClearButton(
                    [question_box, chatbot, session_state],
                    value="New session",
                )
            gr.Examples(EXAMPLE_QUESTIONS, inputs=question_box, label="Demonstration questions")

        with gr.Column(scale=2):
            model_output = gr.Markdown("No request yet.", label="AI interpretation")
            decision_output = gr.Markdown("No decision yet.", label="Decision")
            claims_output = gr.Markdown("No numeric claim was released.", label="Certified claims")
            runtime_output = gr.Markdown(
                f"Configured model: `{MODEL_ID}`. It will load on first use.",
                label="Runtime",
            )
            with gr.Accordion("Verification receipt", open=True):
                receipt_output = gr.JSON(value={}, label="Receipt")
            with gr.Accordion("Business Query IR", open=False):
                query_output = gr.JSON(value={}, label="Query plan")

    outputs = [
        chatbot,
        question_box,
        session_state,
        model_output,
        decision_output,
        claims_output,
        receipt_output,
        query_output,
        runtime_output,
    ]
    ask_button.click(
        ask_question,
        inputs=[question_box, chatbot, session_state],
        outputs=outputs,
        concurrency_limit=1,
    )
    question_box.submit(
        ask_question,
        inputs=[question_box, chatbot, session_state],
        outputs=outputs,
        concurrency_limit=1,
    )

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1, max_size=20).launch()
