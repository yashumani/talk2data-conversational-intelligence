"use strict";

const examples = [
  {
    title: "Postpaid churn",
    question: "What was postpaid churn by plan last month?",
    hint: "Release a verified ratio by an approved business dimension.",
  },
  {
    title: "Activation movement",
    question: "Compare mobile activations in Northeast last month to the previous period.",
    hint: "Compare two resolved reporting periods with deterministic execution.",
  },
  {
    title: "Source coverage",
    question: "What was ARPA last month?",
    hint: "See how the assistant handles a metric whose source is unavailable.",
  },
  {
    title: "Business-sense guardrail",
    question: "What is our restaurant food-cost margin by location?",
    hint: "Test a question outside the approved telecom Domain Pack.",
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
  apiConnectionDetail: document.getElementById("api-connection-detail"),
  connect: document.getElementById("connect"),
  connectionClose: document.getElementById("connection-close"),
  connectionDialog: document.getElementById("connection-dialog"),
  runtime: document.getElementById("runtime"),
  runtimeDetail: document.getElementById("runtime-detail"),
  examples: document.getElementById("examples"),
  chat: document.getElementById("chat"),
  welcome: document.getElementById("welcome"),
  conversationScroll: document.getElementById("conversation-scroll"),
  form: document.getElementById("form"),
  question: document.getElementById("question"),
  send: document.getElementById("send"),
  ai: document.getElementById("ai"),
  decision: document.getElementById("decision"),
  sessionDetail: document.getElementById("session-detail"),
  claims: document.getElementById("claims"),
  receipt: document.getElementById("receipt"),
  plan: document.getElementById("plan"),
  copyEvidence: document.getElementById("copy-evidence"),
  historyList: document.getElementById("history-list"),
  historySearch: document.getElementById("history-search"),
  newChat: document.getElementById("new-chat"),
  openConnection: document.getElementById("open-connection"),
  launcherConnect: document.getElementById("launcher-connect"),
  composerConnect: document.getElementById("composer-connect"),
  modelPicker: document.getElementById("model-picker"),
  profileCard: document.getElementById("profile-card"),
};

const state = {
  apiBase: "",
  connected: false,
  busy: false,
  pendingQuestion: null,
  chats: [],
  activeChatId: null,
  lastEvidence: null,
};

function identifier(prefix) {
  const suffix =
    typeof window.crypto?.randomUUID === "function"
      ? window.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

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

function createChat() {
  const chat = {
    id: identifier("chat"),
    title: "New chat",
    sessionId: null,
    messages: [],
    lastData: null,
    createdAt: new Date(),
  };
  state.chats.unshift(chat);
  state.activeChatId = chat.id;
  state.lastEvidence = null;
  return chat;
}

function currentChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId) || createChat();
}

function summarizeTitle(question) {
  const normalized = String(question).replace(/\s+/g, " ").trim();
  return normalized.length > 52 ? `${normalized.slice(0, 49)}…` : normalized;
}

function setBusy(busy) {
  state.busy = busy;
  elements.question.disabled = busy || !state.connected;
  elements.send.disabled = busy || !state.connected;
  elements.connect.disabled = busy;
  renderConversation();
}

function setConnectionState(connectionState, label, detail) {
  state.connected = connectionState === "ready";
  elements.runtime.textContent = label;
  elements.runtime.className = `status-pill ${connectionState}`;
  elements.runtime.title = detail;
  elements.runtimeDetail.textContent = detail;
  elements.apiConnectionDetail.textContent = detail;
  elements.question.disabled = state.busy || !state.connected;
  elements.send.disabled = state.busy || !state.connected;

  if (state.connected) {
    elements.composerConnect.setAttribute("aria-label", "Runtime connected");
    elements.composerConnect.title = "Runtime connected";
  } else {
    elements.composerConnect.setAttribute("aria-label", "Connect a runtime");
    elements.composerConnect.title = "Connect a runtime";
  }
}

function openConnectionDialog() {
  window.Talk2DataUI.showDialog(elements.connectionDialog);
}

function closeConnectionDialog() {
  window.Talk2DataUI.closeDialog(elements.connectionDialog);
}

function messageMeta(data) {
  const result = [];
  if (data?.status) result.push(data.status);
  if (data?.decision?.verdict) result.push(data.decision.verdict);
  if (data?.receipt?.receipt_id) result.push(`receipt ${data.receipt.receipt_id}`);
  return result;
}

function addMessage(role, text, options = {}) {
  const chat = currentChat();
  chat.messages.push({
    id: identifier("message"),
    role,
    text: String(text),
    meta: options.meta || [],
    evidence: options.evidence || null,
  });
  renderConversation();
}

function createAssistantAvatar() {
  const avatar = document.createElement("div");
  avatar.className = "assistant-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = "T2D";
  return avatar;
}

function createMessageRow(message) {
  const row = document.createElement("article");
  row.className = `message-row ${message.role}`;
  row.dataset.messageId = message.id;

  if (message.role === "assistant") row.appendChild(createAssistantAvatar());

  const container = document.createElement("div");
  const content = document.createElement("div");
  content.className = "message-content";
  content.textContent = message.text;
  container.appendChild(content);

  if (message.meta?.length) {
    const meta = document.createElement("div");
    meta.className = "message-meta";
    for (const value of message.meta) {
      const chip = document.createElement("span");
      chip.className = "meta-chip";
      chip.textContent = value;
      meta.appendChild(chip);
    }
    container.appendChild(meta);
  }

  const actions = document.createElement("div");
  actions.className = "message-actions";

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "message-action";
  copy.textContent = "Copy";
  copy.addEventListener("click", () => {
    void window.Talk2DataUI.copyText(message.text, "Message copied.");
  });
  actions.appendChild(copy);

  if (message.evidence) {
    const inspect = document.createElement("button");
    inspect.type = "button";
    inspect.className = "message-action";
    inspect.textContent = "View evidence";
    inspect.addEventListener("click", () => {
      state.lastEvidence = message.evidence;
      renderPanel(message.evidence);
      window.Talk2DataUI.activateInspectorTab("overview");
    });
    actions.appendChild(inspect);
  }

  container.appendChild(actions);
  row.appendChild(container);
  return row;
}

function createLoadingRow() {
  const row = document.createElement("article");
  row.className = "message-row assistant loading";
  row.appendChild(createAssistantAvatar());

  const content = document.createElement("div");
  content.className = "message-content";
  content.textContent = "Checking policy, semantics, sources, and evidence";
  const dots = document.createElement("span");
  dots.className = "typing-dots";
  dots.setAttribute("aria-label", "Working");
  for (let index = 0; index < 3; index += 1) dots.appendChild(document.createElement("span"));
  content.append(" ", dots);
  row.appendChild(content);
  return row;
}

function renderConversation() {
  const chat = currentChat();
  elements.welcome.hidden = chat.messages.length > 0;
  elements.chat.textContent = "";

  for (const message of chat.messages) {
    elements.chat.appendChild(createMessageRow(message));
  }
  if (state.busy) elements.chat.appendChild(createLoadingRow());

  window.requestAnimationFrame(() => {
    elements.conversationScroll.scrollTop =
      chat.messages.length || state.busy ? elements.conversationScroll.scrollHeight : 0;
  });
}

function renderHistory() {
  const query = elements.historySearch.value.trim().toLowerCase();
  const visible = state.chats.filter(
    (chat) => chat.messages.length && (!query || chat.title.toLowerCase().includes(query)),
  );
  elements.historyList.textContent = "";

  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = query
      ? "No chat title matches this search."
      : "Your chat titles will appear here after you ask a question. Conversation content is not written to local storage.";
    elements.historyList.appendChild(empty);
    return;
  }

  const label = document.createElement("div");
  label.className = "history-group-label";
  label.textContent = "Today";
  elements.historyList.appendChild(label);

  for (const chat of visible) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    button.classList.toggle("active", chat.id === state.activeChatId);
    button.setAttribute("role", "listitem");
    button.title = chat.title;

    const title = document.createElement("span");
    title.className = "history-title";
    title.textContent = chat.title;
    button.appendChild(title);

    button.addEventListener("click", () => {
      state.activeChatId = chat.id;
      state.lastEvidence = chat.lastData;
      renderHistory();
      renderConversation();
      renderPanel(chat.lastData);
      window.Talk2DataUI.closeMobilePanels();
    });
    elements.historyList.appendChild(button);
  }
}

function renderPanel(data) {
  elements.copyEvidence.disabled = !data;
  if (!data) {
    elements.ai.textContent = "No request yet.";
    elements.decision.textContent = "—";
    elements.sessionDetail.textContent = "A session will begin with your first question.";
    elements.claims.textContent = "";
    const empty = document.createElement("div");
    empty.className = "card-value";
    empty.textContent = "No numeric claim released.";
    elements.claims.appendChild(empty);
    elements.receipt.textContent = "No receipt issued.";
    elements.plan.textContent = "No executable plan.";
    return;
  }

  const mode = data.decision?.interpreter_mode || "unknown interpreter";
  const model = data.ai_model ? ` · ${data.ai_model}` : "";
  elements.ai.textContent = `${mode}${model}`;
  elements.decision.textContent = `${data.status || "unknown"} · ${data.decision?.verdict || "no verdict"}`;
  elements.sessionDetail.textContent = data.session_id || "No session ID returned.";
  elements.claims.textContent = "";

  const claims = data.answer?.claims || [];
  if (!claims.length) {
    const empty = document.createElement("div");
    empty.className = "card-value";
    empty.textContent = "No numeric claim released.";
    elements.claims.appendChild(empty);
  } else {
    for (const item of claims) {
      const node = document.createElement("div");
      node.className = "claim";
      node.textContent = item.statement || "Certified claim";
      elements.claims.appendChild(node);
    }
  }

  elements.receipt.textContent = data.receipt
    ? JSON.stringify(data.receipt, null, 2)
    : "No receipt issued.";
  elements.plan.textContent = data.query_ir
    ? JSON.stringify(data.query_ir, null, 2)
    : "No executable plan.";
}

async function parseResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

async function connect() {
  state.apiBase = normalizeBaseUrl(elements.apiBase.value);
  if (!state.apiBase) {
    setConnectionState(
      "failed",
      "URL required",
      "Enter the forwarded HTTPS URL for a running Talk2Data API.",
    );
    return;
  }

  elements.connect.disabled = true;
  elements.connect.textContent = "Connecting…";
  setConnectionState("degraded", "Connecting", `Checking ${state.apiBase}`);

  try {
    const response = await fetch(`${state.apiBase}/health/ready`, {
      headers: { Accept: "application/json" },
    });
    const data = await parseResponse(response);
    const ollama = data.components?.ollama;
    if (data.status !== "ready" || ollama?.status !== "ready") {
      throw new Error(ollama?.detail || `Runtime readiness is ${data.status || "unknown"}.`);
    }

    window.localStorage.setItem("talk2data.apiBase", state.apiBase);
    setConnectionState(
      "ready",
      "Ollama ready",
      `${state.apiBase} · ${ollama.detail || "Local model and governed services are ready."}`,
    );
    closeConnectionDialog();
    window.Talk2DataUI.showToast("Talk2Data runtime connected.");

    const queued = state.pendingQuestion;
    state.pendingQuestion = null;
    if (queued) await ask(queued);
    else elements.question.focus({ preventScroll: true });
  } catch (error) {
    setConnectionState(
      "failed",
      "Runtime unavailable",
      `${error.message} Confirm HTTPS, CORS, port visibility, and /health/ready.`,
    );
  } finally {
    elements.connect.disabled = false;
    elements.connect.textContent = "Connect runtime";
  }
}

async function ask(rawText) {
  const text = String(rawText || "").trim();
  if (!text) return;

  if (!state.connected) {
    state.pendingQuestion = text;
    elements.apiConnectionDetail.textContent = "Connect the runtime to run the queued business question.";
    openConnectionDialog();
    window.Talk2DataUI.showToast("Connect a Talk2Data runtime before sending this question.");
    return;
  }

  const chat = currentChat();
  if (!chat.messages.length) {
    chat.title = summarizeTitle(text);
  }

  addMessage("user", text);
  renderHistory();
  setBusy(true);

  try {
    const response = await fetch(`${state.apiBase}/v1/chat/demo`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        question: text,
        access_context: access,
        session_id: chat.sessionId,
        use_llm: true,
        include_debug: true,
        as_of: "2026-08-17T12:00:00Z",
      }),
    });
    const data = await parseResponse(response);
    chat.sessionId = data.session_id || chat.sessionId;
    chat.lastData = data;
    state.lastEvidence = data;
    addMessage("assistant", data.message || "Talk2Data completed the request.", {
      meta: messageMeta(data),
      evidence: data,
    });
    renderPanel(data);
  } catch (error) {
    addMessage(
      "assistant",
      `Talk2Data request failed: ${error.message}`,
      { meta: ["request failed"] },
    );
    window.Talk2DataUI.showToast("The request failed. Check the runtime and try again.");
  } finally {
    setBusy(false);
    elements.question.focus({ preventScroll: true });
  }
}

function startNewChat() {
  const active = currentChat();
  if (!active.messages.length) {
    active.sessionId = null;
    active.lastData = null;
    state.lastEvidence = null;
  } else {
    createChat();
  }
  elements.question.value = "";
  window.Talk2DataUI.autoGrow(elements.question);
  renderHistory();
  renderConversation();
  renderPanel(null);
  window.Talk2DataUI.closeMobilePanels();
  if (state.connected) elements.question.focus({ preventScroll: true });
}

function renderExamples() {
  elements.examples.textContent = "";
  for (const item of examples) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "prompt-card";

    const title = document.createElement("strong");
    title.textContent = item.title;
    const question = document.createElement("span");
    question.textContent = item.question;
    button.append(title, question);
    button.title = item.hint;
    button.addEventListener("click", () => void ask(item.question));
    elements.examples.appendChild(button);
  }
}

function evidencePackage(data) {
  if (!data) return null;
  return {
    status: data.status,
    session_id: data.session_id,
    ai_model: data.ai_model,
    decision: data.decision,
    answer: data.answer,
    receipt: data.receipt,
    query_ir: data.query_ir,
  };
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.question.value.trim();
  if (!text) return;
  elements.question.value = "";
  window.Talk2DataUI.autoGrow(elements.question);
  void ask(text);
});

elements.question.addEventListener("input", () => window.Talk2DataUI.autoGrow(elements.question));
elements.question.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});

elements.connect.addEventListener("click", () => void connect());
elements.connectionClose.addEventListener("click", closeConnectionDialog);
elements.newChat.addEventListener("click", startNewChat);
elements.historySearch.addEventListener("input", renderHistory);
for (const trigger of [
  elements.openConnection,
  elements.launcherConnect,
  elements.composerConnect,
  elements.modelPicker,
]) {
  trigger.addEventListener("click", openConnectionDialog);
}

elements.copyEvidence.addEventListener("click", () => {
  const payload = evidencePackage(state.lastEvidence);
  if (!payload) return;
  void window.Talk2DataUI.copyText(JSON.stringify(payload, null, 2), "Evidence package copied.");
});

elements.profileCard.addEventListener("click", () => {
  window.Talk2DataUI.showToast(
    "Synthetic evaluation identity · demo-telecom · BUSINESS_INTELLIGENCE · RESTRICTED",
  );
});

createChat();
renderExamples();
renderHistory();
renderConversation();
renderPanel(null);

state.apiBase = configuredBaseUrl();
elements.apiBase.value = state.apiBase;
if (state.apiBase) {
  void connect();
} else {
  setConnectionState(
    "degraded",
    "Runtime offline",
    "Launch the full runtime in Codespaces or connect an existing Talk2Data API.",
  );
}
