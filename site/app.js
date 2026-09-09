"use strict";

const previewScenarios = [
  {
    question: "What were mobile activations by region last month?",
    message:
      "Mobile Activations totaled 24,676 in July 2026. By region: West 7,099; Central 6,479; Southeast 5,859; Northeast 5,239.",
    status: "ANSWERED",
    verdict: "VERIFIED PREVIEW",
    claims: [
      "July 2026 total: 24,676 activations",
      "West 7,099 · Central 6,479",
      "Southeast 5,859 · Northeast 5,239",
    ],
    query_ir: {
      metric_id: "MOBILE_ACTIVATIONS",
      definition: "Completed new connections",
      period: { start: "2026-07-01", end: "2026-07-31" },
      group_by: ["REGION"],
      aggregation: "SUM",
    },
    preview_receipt: {
      preview: true,
      source: "apps/web/public/samples/mobile-activations.csv",
      source_rows: 736,
      period_rows: 248,
      result_total: 24676,
      note: "Checked-in synthetic acceptance fixture; not a live receipt.",
    },
  },
  {
    question: "Compare mobile activations last month to the previous period.",
    message:
      "Mobile Activations increased from 23,400 in June 2026 to 24,676 in July 2026: +1,276, or +5.45%.",
    status: "ANSWERED",
    verdict: "VERIFIED PREVIEW",
    claims: [
      "July 2026: 24,676 activations",
      "June 2026: 23,400 activations",
      "Change: +1,276 (+5.45%)",
    ],
    query_ir: {
      metric_id: "MOBILE_ACTIVATIONS",
      period: { start: "2026-07-01", end: "2026-07-31" },
      comparison_period: { start: "2026-06-01", end: "2026-06-30" },
      aggregation: "SUM",
    },
    preview_receipt: {
      preview: true,
      source: "apps/web/public/samples/mobile-activations.csv",
      source_rows: 736,
      current_total: 24676,
      comparison_total: 23400,
      note: "Checked-in synthetic acceptance fixture; not a live receipt.",
    },
  },
  {
    question: "What were mobile activations in Northeast last month?",
    message: "Mobile Activations in the Northeast were 5,239 in July 2026.",
    status: "ANSWERED",
    verdict: "VERIFIED PREVIEW",
    claims: ["Northeast · July 2026: 5,239 activations"],
    query_ir: {
      metric_id: "MOBILE_ACTIVATIONS",
      period: { start: "2026-07-01", end: "2026-07-31" },
      filters: [{ dimension_id: "REGION", values: ["NORTHEAST"] }],
      aggregation: "SUM",
    },
    preview_receipt: {
      preview: true,
      source: "apps/web/public/samples/mobile-activations.csv",
      source_rows: 736,
      result_total: 5239,
      note: "Checked-in synthetic acceptance fixture; not a live receipt.",
    },
  },
  {
    question: "What was postpaid churn last month?",
    message:
      "I cannot answer that from this CSV workspace. Postpaid Churn is not an available metric in the selected source, so Talk2Data abstains instead of guessing.",
    status: "OUT_OF_DOMAIN",
    verdict: "ABSTAINED",
    claims: [],
    query_ir: null,
    preview_receipt: null,
  },
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
  sourceIcon: document.getElementById("source-icon"),
  sourceTitle: document.getElementById("source-title"),
  sourceDetail: document.getElementById("source-detail"),
  sourceState: document.getElementById("source-state"),
  examples: document.getElementById("examples"),
  chat: document.getElementById("chat"),
  form: document.getElementById("form"),
  question: document.getElementById("question"),
  send: document.getElementById("send"),
  tourNote: document.getElementById("tour-note"),
  ai: document.getElementById("ai"),
  decision: document.getElementById("decision"),
  claims: document.getElementById("claims"),
  receipt: document.getElementById("receipt"),
  plan: document.getElementById("plan"),
};

let apiBase = "";
let sessionId = null;
let connected = false;
let busy = false;

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function normalizeBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function validateBaseUrl(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Enter a complete HTTPS runtime URL");
  }
  const localHttp =
    parsed.protocol === "http:" && ["localhost", "127.0.0.1"].includes(parsed.hostname);
  if (parsed.protocol !== "https:" && !localHttp) {
    throw new Error("Public runtime URLs must use HTTPS; HTTP is allowed only on localhost");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("Runtime URLs cannot contain credentials, a query, or a fragment");
  }
  return normalizeBaseUrl(parsed.href);
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

function setStatus(state, label, detail) {
  elements.runtime.textContent = label;
  elements.runtime.className = `status ${state}`;
  elements.runtimeDetail.textContent = detail;
}

function setBusy(value) {
  busy = value;
  elements.send.disabled = value;
  elements.connect.disabled = value;
  for (const button of elements.examples.querySelectorAll("button")) {
    button.disabled = value;
  }
}

function addMessage(role, message, meta = "", preview = false) {
  const box = document.createElement("div");
  box.className = `message ${role}${preview ? " preview-message" : ""}`;
  box.textContent = message;
  if (meta) {
    const detail = document.createElement("div");
    detail.className = "meta";
    detail.textContent = meta;
    box.appendChild(detail);
  }
  elements.chat.appendChild(box);
  elements.chat.scrollTop = elements.chat.scrollHeight;
}

function renderClaims(claims) {
  elements.claims.textContent = "";
  if (!claims.length) {
    elements.claims.textContent = "No numeric claim released.";
    return;
  }
  for (const statement of claims) {
    const node = document.createElement("div");
    node.className = "claim";
    node.textContent = statement;
    elements.claims.appendChild(node);
  }
}

function renderPreviewSource() {
  elements.sourceIcon.textContent = "CSV";
  elements.sourceTitle.textContent = "Mobile Activations";
  elements.sourceDetail.textContent = "736 synthetic rows · May–July 2026";
  elements.sourceState.textContent = "Definition published";
}

function renderLiveSource() {
  elements.sourceIcon.textContent = "API";
  elements.sourceTitle.textContent = "Connected evaluation runtime";
  elements.sourceDetail.textContent = apiBase;
  elements.sourceState.textContent = "Server evidence required";
}

function renderPendingEvidence() {
  elements.ai.textContent = "Waiting for governed interpretation";
  elements.decision.textContent = "RUNNING";
  renderClaims([]);
  elements.receipt.textContent = "Pending — no receipt has been issued for this question.";
  elements.plan.textContent = "Pending — no executable plan has been accepted yet.";
}

function renderFailedEvidence(message) {
  elements.ai.textContent = "Request failed before verified release";
  elements.decision.textContent = "FAILED · NO RELEASE";
  renderClaims([]);
  elements.receipt.textContent = `No receipt issued. ${message}`;
  elements.plan.textContent = "No executable plan released.";
}

function renderPreview(scenario, announceQuestion = true) {
  renderPreviewSource();
  if (announceQuestion) addMessage("user", scenario.question);
  addMessage(
    "assistant",
    scenario.message,
    "Static UI preview · run the workspace for a live receipt",
    true,
  );
  elements.ai.textContent = "Rules preview · no model call";
  elements.decision.textContent = scenario.verdict;
  renderClaims(scenario.claims);
  elements.receipt.textContent = scenario.preview_receipt
    ? JSON.stringify(scenario.preview_receipt, null, 2)
    : "No receipt issued because no numeric claim was released.";
  elements.plan.textContent = scenario.query_ir
    ? JSON.stringify(scenario.query_ir, null, 2)
    : "No executable plan.";
  setStatus("preview", "Fixture preview", "Preview — checked-in synthetic fixture");
}

function renderLive(data) {
  const model = data.ai_model ? ` · ${data.ai_model}` : "";
  elements.ai.textContent = `${data.decision.interpreter_mode}${model}`;
  elements.decision.textContent = `${data.status} · ${data.decision.verdict}`;
  renderClaims((data.answer?.claims || []).map((item) => item.statement));
  elements.receipt.textContent = data.receipt
    ? JSON.stringify(data.receipt, null, 2)
    : "No receipt issued.";
  elements.plan.textContent = data.query_ir
    ? JSON.stringify(data.query_ir, null, 2)
    : "No executable plan.";
}

function findPreview(question) {
  const normalized = question.trim().toLowerCase();
  return previewScenarios.find((item) => item.question.toLowerCase() === normalized) || null;
}

function runtimeSummary(data) {
  const ready = Object.entries(data.components || {})
    .filter(([, value]) => value?.status === "ready")
    .map(([name]) => name.replaceAll("_", " "));
  return ready.length ? ready.join(", ") : "governed API";
}

async function connect() {
  const requestedBaseUrl = normalizeBaseUrl(elements.apiBase.value);
  sessionId = null;
  connected = false;
  if (!requestedBaseUrl) {
    apiBase = "";
    renderPreview(previewScenarios[0], false);
    setStatus("preview", "Fixture preview", "Enter an approved public evaluation API URL to connect.");
    elements.tourNote.textContent =
      "Preview mode recognizes only the published examples. It never invents an answer.";
    return;
  }

  try {
    apiBase = validateBaseUrl(requestedBaseUrl);
  } catch (error) {
    renderPreviewSource();
    renderFailedEvidence(error.message);
    setStatus("failed", "Invalid runtime URL", error.message);
    elements.tourNote.textContent =
      "The checked-in fixture preview remains available and does not send data.";
    return;
  }

  setBusy(true);
  setStatus("degraded", "Connecting…", `Checking ${apiBase}`);
  try {
    const response = await fetchWithTimeout(
      `${apiBase}/health/ready`,
      { headers: { Accept: "application/json" } },
      10000,
    );
    if (!response.ok) throw new Error(`Readiness returned HTTP ${response.status}`);
    const data = await response.json();
    if (data.status !== "ready") throw new Error(`Runtime readiness is ${data.status || "unknown"}`);
    connected = true;
    window.localStorage.setItem("talk2data.apiBase", apiBase);
    renderLiveSource();
    setStatus("ready", "Live runtime", `${apiBase} · ${runtimeSummary(data)} ready`);
    elements.tourNote.textContent = "Live mode: responses and receipts come from the connected governed runtime.";
    addMessage("assistant", "The public evaluation runtime is ready. New questions will run live.");
  } catch (error) {
    renderPreviewSource();
    renderFailedEvidence(error.message);
    setStatus("failed", "Connection failed", `${error.message}. Preview mode remains available.`);
    elements.tourNote.textContent = "Connection failed. The checked-in fixture preview remains available and does not send data.";
    addMessage("assistant", `The live runtime could not be reached: ${error.message}`, "No question or data was sent.");
  } finally {
    setBusy(false);
  }
}

async function askLive(text) {
  addMessage("user", text);
  renderPendingEvidence();
  setBusy(true);
  try {
    const response = await fetchWithTimeout(
      `${apiBase}/v1/chat/demo`,
      {
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
      },
      60000,
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    sessionId = data.session_id;
    const receiptId = data.receipt?.receipt_id || "not issued";
    addMessage("assistant", data.message, `${data.status} · receipt ${receiptId}`);
    renderLive(data);
  } catch (error) {
    renderFailedEvidence(error.message);
    addMessage(
      "assistant",
      `Talk2Data request failed: ${error.message}`,
      "No numeric claim was released. Check the API, HTTPS, and CORS configuration.",
    );
  } finally {
    setBusy(false);
  }
}

async function ask(text) {
  if (busy) return;
  if (connected) {
    await askLive(text);
    return;
  }
  const scenario = findPreview(text);
  if (scenario) {
    renderPreview(scenario);
    return;
  }
  addMessage("user", text);
  addMessage(
    "assistant",
    "This static product tour does not calculate new answers. Choose one of the published examples, launch the CSV workspace, or connect an approved public evaluation API.",
    "Preview mode abstained · no numeric claim released",
    true,
  );
  elements.decision.textContent = "PREVIEW · ABSTAINED";
  renderClaims([]);
  elements.receipt.textContent = "No receipt issued.";
  elements.plan.textContent = "No executable plan.";
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.question.value.trim();
  if (!text) return;
  elements.question.value = "";
  void ask(text);
});

elements.connect.addEventListener("click", () => void connect());

for (const scenario of previewScenarios) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = scenario.question;
  button.addEventListener("click", () => {
    elements.question.value = scenario.question;
    void ask(scenario.question);
  });
  elements.examples.appendChild(button);
}

apiBase = configuredBaseUrl();
elements.apiBase.value = apiBase;
renderPreview(previewScenarios[0], false);
if (apiBase) void connect();
