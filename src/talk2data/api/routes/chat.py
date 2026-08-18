from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from talk2data.domain.chat import DemoChatRequest, DemoChatResponse
from talk2data.domain.domain_pack import DomainPackNotFoundError
from talk2data.services.demo_chat import DemoChatService
from talk2data.services.interpreter import InterpretationError
from talk2data.services.session_store import SessionAccessDeniedError, SessionNotFoundError

router = APIRouter(tags=["chat-demo"])


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/demo", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
async def demo_page() -> HTMLResponse:
    return HTMLResponse(DEMO_HTML)


@router.post(
    "/v1/chat/demo",
    response_model=DemoChatResponse,
    summary="Run the receipt-backed Talk2Data demonstration chat path",
)
async def demo_chat(payload: DemoChatRequest, request: Request) -> DemoChatResponse:
    service = cast(DemoChatService, request.app.state.demo_chat_service)
    try:
        return await service.answer(payload)
    except DomainPackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SessionAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session access denied.",
        ) from exc
    except InterpretationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The required local Ollama interpretation service is unavailable.",
        ) from exc


DEMO_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Talk2Data AI Demo</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #090b10; color: #f5f7fb; min-height: 100vh; }
    .shell { display: grid; grid-template-columns: minmax(0, 1fr) 360px; min-height: 100vh; }
    main { padding: 28px; display: flex; flex-direction: column; gap: 18px; }
    aside { border-left: 1px solid #242936; background: #0d1118; padding: 24px; overflow: auto; }
    .brand { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    h1 { font-size: clamp(28px, 4vw, 48px); margin: 0; letter-spacing: -0.04em; }
    .subtitle { margin: 8px 0 0; color: #aeb8ca; max-width: 780px; }
    .status { padding: 8px 12px; border: 1px solid #343b4b; border-radius: 999px; font-size: 13px; }
    .status.ready { border-color: #3a8b69; color: #8cf0c1; }
    .status.degraded { border-color: #8a6b36; color: #ffd68b; }
    .chat { flex: 1; min-height: 420px; border: 1px solid #252b38; border-radius: 18px; padding: 18px; overflow: auto; background: #0c1017; }
    .message { max-width: 850px; padding: 14px 16px; margin: 10px 0; border-radius: 15px; line-height: 1.5; white-space: pre-wrap; }
    .user { margin-left: auto; background: #3158d8; }
    .assistant { background: #171d28; border: 1px solid #283142; }
    .meta { color: #9eabc0; font-size: 12px; margin-top: 8px; }
    form { display: flex; gap: 10px; }
    textarea { flex: 1; min-height: 76px; resize: vertical; border-radius: 14px; border: 1px solid #303848; background: #10151e; color: #fff; padding: 14px; font: inherit; }
    button { border: 0; border-radius: 12px; background: #d8ff62; color: #10130a; padding: 0 22px; font-weight: 800; cursor: pointer; }
    button:disabled { opacity: .5; cursor: wait; }
    .examples { display: flex; flex-wrap: wrap; gap: 8px; }
    .example { background: transparent; color: #dbe4f5; border: 1px solid #30394a; padding: 8px 11px; font-weight: 500; }
    h2 { margin: 0 0 14px; font-size: 17px; }
    .card { border: 1px solid #252d3b; border-radius: 14px; padding: 14px; margin-bottom: 12px; background: #111720; }
    .label { color: #8e9bb0; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
    pre { white-space: pre-wrap; word-break: break-word; color: #bfcae0; font-size: 11px; max-height: 240px; overflow: auto; }
    .claim { border-left: 3px solid #d8ff62; padding-left: 10px; margin: 9px 0; color: #dce5f5; }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; }
      aside { border-left: 0; border-top: 1px solid #242936; }
      main { padding: 18px; }
      form { flex-direction: column; }
      button { min-height: 48px; }
    }
  </style>
</head>
<body>
<div class="shell">
  <main>
    <header class="brand">
      <div>
        <h1>Talk2Data</h1>
        <p class="subtitle">Local Ollama interpretation, governed semantics, parameterized data execution, and receipt-backed answers. AI Brain context is intentionally disconnected for this demo.</p>
      </div>
      <span id="runtime" class="status">Checking runtime…</span>
    </header>
    <div class="examples" id="examples"></div>
    <section id="chat" class="chat" aria-live="polite">
      <div class="message assistant">Ask a telecom business question. I will either return a verified answer, request clarification, or abstain.</div>
    </section>
    <form id="form">
      <textarea id="question" maxlength="8000" placeholder="Example: What was postpaid churn by plan last month?" required></textarea>
      <button id="send" type="submit">Ask</button>
    </form>
  </main>
  <aside>
    <h2>Verification panel</h2>
    <div class="card"><div class="label">AI interpretation</div><div id="ai">No request yet</div></div>
    <div class="card"><div class="label">Decision</div><div id="decision">—</div></div>
    <div class="card"><div class="label">Certified claims</div><div id="claims">—</div></div>
    <div class="card"><div class="label">Receipt</div><pre id="receipt">—</pre></div>
    <div class="card"><div class="label">Query plan</div><pre id="plan">—</pre></div>
  </aside>
</div>
<script>
const examples = [
  "What was postpaid churn by plan last month?",
  "Compare mobile activations in Northeast last month to the previous period.",
  "What were mobile activations this month?",
  "What was ARPA last month?",
  "What is our restaurant food-cost margin by location?",
  "Did food-delivery application traffic contribute to network congestion?"
];
const access = {
  tenant_id: "demo-telecom", user_id: "demo-user", roles: ["TALK2DATA_ADMIN"],
  departments: ["BUSINESS_INTELLIGENCE"], regions: ["NORTH_AMERICA"],
  business_units: ["CONSUMER"], classification_clearance: "RESTRICTED",
  permitted_actions: ["ASK_BUSINESS_QUESTIONS", "READ_AGGREGATED_DATA", "USE_EXTERNAL_CONTEXT"]
};
let sessionId = null;
const chat = document.getElementById("chat");
const form = document.getElementById("form");
const question = document.getElementById("question");
const send = document.getElementById("send");

function addMessage(role, text, meta="") {
  const box = document.createElement("div");
  box.className = `message ${role}`;
  box.textContent = text;
  if (meta) {
    const detail = document.createElement("div");
    detail.className = "meta";
    detail.textContent = meta;
    box.appendChild(detail);
  }
  chat.appendChild(box);
  chat.scrollTop = chat.scrollHeight;
}

function renderPanel(data) {
  document.getElementById("ai").textContent = `${data.decision.interpreter_mode}${data.ai_model ? ` · ${data.ai_model}` : ""}`;
  document.getElementById("decision").textContent = `${data.status} · ${data.decision.verdict}`;
  const claims = document.getElementById("claims");
  claims.textContent = "";
  const items = data.answer?.claims || [];
  if (!items.length) claims.textContent = "No numeric claim released.";
  for (const item of items) {
    const node = document.createElement("div");
    node.className = "claim";
    node.textContent = item.statement;
    claims.appendChild(node);
  }
  document.getElementById("receipt").textContent = data.receipt ? JSON.stringify(data.receipt, null, 2) : "No receipt.";
  document.getElementById("plan").textContent = data.query_ir ? JSON.stringify(data.query_ir, null, 2) : "No executable plan.";
}

async function ask(text) {
  addMessage("user", text);
  send.disabled = true;
  try {
    const response = await fetch("/v1/chat/demo", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        question: text, access_context: access, session_id: sessionId,
        use_llm: true, include_debug: true, as_of: "2026-08-17T12:00:00Z"
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    sessionId = data.session_id;
    addMessage("assistant", data.message, `${data.status} · receipt ${data.receipt?.receipt_id || "not issued"}`);
    renderPanel(data);
  } catch (error) {
    addMessage("assistant", `Demo request failed: ${error.message}`, "Check Ollama and API readiness.");
  } finally {
    send.disabled = false;
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  const text = question.value.trim();
  if (!text) return;
  question.value = "";
  ask(text);
});

for (const text of examples) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "example";
  button.textContent = text;
  button.addEventListener("click", () => ask(text));
  document.getElementById("examples").appendChild(button);
}

fetch("/health/ready").then(response => response.json()).then(data => {
  const runtime = document.getElementById("runtime");
  const ollama = data.components?.ollama;
  runtime.textContent = ollama?.status === "ready" ? "Ollama ready" : `Runtime ${ollama?.status || data.status}`;
  runtime.className = `status ${ollama?.status === "ready" ? "ready" : "degraded"}`;
  runtime.title = ollama?.detail || "";
}).catch(() => {
  const runtime = document.getElementById("runtime");
  runtime.textContent = "Runtime unavailable";
  runtime.className = "status degraded";
});
</script>
</body>
</html>"""
