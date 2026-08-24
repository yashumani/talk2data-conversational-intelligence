"use strict";

const examples = [
  "What was postpaid churn by plan last month?",
  "Compare mobile activations in Northeast last month to the previous period.",
  "What were mobile activations this month?",
  "What was ARPA last month?",
  "What is our restaurant food-cost margin by location?",
  "Did food-delivery application traffic contribute to network congestion?",
];

function browserPrincipal() {
  const key = "talk2data.browserPrincipal";
  let value = window.localStorage.getItem(key);
  if (!value) {
    const suffix =
      typeof window.crypto?.randomUUID === "function"
        ? window.crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    value = `pages-${suffix}`;
    window.localStorage.setItem(key, value);
  }
  return value;
}

const access = {
  tenant_id: "demo-telecom",
  user_id: browserPrincipal(),
  roles: ["TALK2DATA_ADMIN"],
  departments: ["BUSINESS_INTELLIGENCE"],
  regions: ["NORTH_AMERICA"],
  business_units: ["CONSUMER"],
  classification_clearance: "RESTRICTED",
  permitted_actions: [
    "ASK_BUSINESS_QUESTIONS",
    "READ_AGGREGATED_DATA",
    "USE_EXTERNAL_CONTEXT",
  ],
};

const elements = {
  apiBase: document.getElementById("api-base"),
  connect: document.getElementById("connect"),
  runtime: document.getElementById("runtime"),
  runtimeDetail: document.getElementById("runtime-detail"),
  examples: document.getElementById("examples"),
  chat: document.getElementById("chat"),
  form: document.getElementById("form"),
  question: document.getElementById("question"),
  send: document.getElementById("send"),
  ai: document.getElementById("ai"),
  decision: document.getElementById("decision"),
  claims: document.getElementById("claims"),
  receipt: document.getElementById("receipt"),
  plan: document.getElementById("plan"),
};

let apiBase = "";
let sessionId = null;
let connected = false;

function normalizeBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function configuredBaseUrl() {
  const params = new URLSearchParams(window.location.search);
  return normalizeBaseUrl(
    params.get("api") ||
      window.localStorage.getItem("talk2data.apiBase") ||
      window.T2D_PUBLIC_API_BASE_URL ||
      "",
  );
}

function setConnectionState(state, label, detail) {
  connected = state === "ready";
  elements.runtime.textContent = label;
  elements.runtime.className = `status ${state}`;
  elements.runtimeDetail.textContent = detail;
  elements.question.disabled = !connected;
  elements.send.disabled = !connected;
  for (const button of elements.examples.querySelectorAll("button")) {
    button.disabled = !connected;
  }
}

function addMessage(role, text, meta = "") {
  const box = document.createElement("div");
  box.className = `message ${role}`;
  box.textContent = text;
  if (meta) {
    const detail = document.createElement("div");
    detail.className = "meta";
    detail.textContent = meta;
    box.appendChild(detail);
  }
  elements.chat.appendChild(box);
  elements.chat.scrollTop = elements.chat.scrollHeight;
}

function renderPanel(data) {
  const model = data.ai_model ? ` · ${data.ai_model}` : "";
  elements.ai.textContent = `${data.decision.interpreter_mode}${model}`;
  elements.decision.textContent = `${data.status} · ${data.decision.verdict}`;
  elements.claims.textContent = "";

  const claims = data.answer?.claims || [];
  if (!claims.length) {
    elements.claims.textContent = "No numeric claim released.";
  }
  for (const item of claims) {
    const node = document.createElement("div");
    node.className = "claim";
    node.textContent = item.statement;
    elements.claims.appendChild(node);
  }

  elements.receipt.textContent = data.receipt
    ? JSON.stringify(data.receipt, null, 2)
    : "No receipt issued.";
  elements.plan.textContent = data.query_ir
    ? JSON.stringify(data.query_ir, null, 2)
    : "No executable plan.";
}

async function connect() {
  apiBase = normalizeBaseUrl(elements.apiBase.value);
  sessionId = null;
  if (!apiBase) {
    setConnectionState(
      "degraded",
      "GitHub launcher",
      "Launch Codespaces above or enter an existing Talk2Data API URL.",
    );
    return;
  }

  elements.connect.disabled = true;
  setConnectionState("degraded", "Connecting…", `Checking ${apiBase}`);
  try {
    const response = await fetch(`${apiBase}/health/ready`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Readiness returned HTTP ${response.status}`);
    }
    const data = await response.json();
    const ollama = data.components?.ollama;
    if (data.status !== "ready" || ollama?.status !== "ready") {
      throw new Error(ollama?.detail || `Runtime is ${data.status}`);
    }
    window.localStorage.setItem("talk2data.apiBase", apiBase);
    setConnectionState(
      "ready",
      "Ollama ready",
      `${apiBase} · ${ollama.detail || "Local model is ready."}`,
    );
    addMessage(
      "assistant",
      "The governed Talk2Data runtime is connected. You can now ask a question.",
    );
  } catch (error) {
    setConnectionState(
      "failed",
      "Runtime unavailable",
      `${error.message}. Confirm the runtime URL, HTTPS, CORS, and readiness.`,
    );
  } finally {
    elements.connect.disabled = false;
  }
}

async function ask(text) {
  if (!connected) {
    addMessage(
      "assistant",
      "Launch the GitHub Codespaces runtime or connect an existing Talk2Data API first.",
    );
    return;
  }

  addMessage("user", text);
  elements.send.disabled = true;
  try {
    const response = await fetch(`${apiBase}/v1/chat/demo`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        question: text,
        access_context: access,
        session_id: sessionId,
        use_llm: true,
        include_debug: true,
        as_of: "2026-08-17T12:00:00Z",
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    sessionId = data.session_id;
    const receiptId = data.receipt?.receipt_id || "not issued";
    addMessage("assistant", data.message, `${data.status} · receipt ${receiptId}`);
    renderPanel(data);
  } catch (error) {
    addMessage(
      "assistant",
      `Talk2Data request failed: ${error.message}`,
      "Check the API, Ollama, HTTPS, and CORS configuration.",
    );
  } finally {
    elements.send.disabled = !connected;
  }
}

function installSetupLink() {
  const actions = document.querySelector(".execution .actions");
  if (!actions || actions.querySelector("[data-setup-link]")) return;
  const link = document.createElement("a");
  link.className = "action";
  link.href = "./setup/";
  link.textContent = "Configure a data source";
  link.dataset.setupLink = "true";
  actions.appendChild(link);
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.question.value.trim();
  if (!text) return;
  elements.question.value = "";
  void ask(text);
});

elements.connect.addEventListener("click", () => void connect());

for (const text of examples) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = text;
  button.disabled = true;
  button.addEventListener("click", () => void ask(text));
  elements.examples.appendChild(button);
}

installSetupLink();
apiBase = configuredBaseUrl();
elements.apiBase.value = apiBase;
if (apiBase) {
  void connect();
} else {
  setConnectionState(
    "degraded",
    "GitHub launcher",
    "Launch the full runtime in Codespaces or connect an existing API.",
  );
}
