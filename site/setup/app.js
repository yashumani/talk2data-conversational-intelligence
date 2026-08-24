"use strict";

function browserPrincipal() {
  const key = "talk2data.setupPrincipal";
  let value = window.localStorage.getItem(key);
  if (!value) {
    const suffix =
      typeof window.crypto?.randomUUID === "function"
        ? window.crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    value = `setup-${suffix}`;
    window.localStorage.setItem(key, value);
  }
  return value;
}

const accessContext = {
  tenant_id: "demo-telecom",
  user_id: browserPrincipal(),
  roles: ["TALK2DATA_ADMIN"],
  departments: ["BUSINESS_INTELLIGENCE"],
  regions: ["NORTH_AMERICA"],
  business_units: ["CONSUMER"],
  classification_clearance: "RESTRICTED",
  permitted_actions: ["ASK_BUSINESS_QUESTIONS", "READ_AGGREGATED_DATA"],
};

const elements = {
  apiBase: document.getElementById("api-base"),
  connect: document.getElementById("connect"),
  form: document.getElementById("setup-form"),
  projectName: document.getElementById("project-name"),
  projectSlug: document.getElementById("project-slug"),
  apiPort: document.getElementById("api-port"),
  modelId: document.getElementById("model-id"),
  modelTimeout: document.getElementById("model-timeout"),
  schemaName: document.getElementById("schema-name"),
  tableName: document.getElementById("table-name"),
  secretName: document.getElementById("secret-name"),
  factDateColumn: document.getElementById("fact-date-column"),
  periodEndColumn: document.getElementById("period-end-column"),
  metricIdColumn: document.getElementById("metric-id-column"),
  amountColumn: document.getElementById("amount-column"),
  numeratorColumn: document.getElementById("numerator-column"),
  denominatorColumn: document.getElementById("denominator-column"),
  planColumn: document.getElementById("plan-column"),
  marketColumn: document.getElementById("market-column"),
  regionColumn: document.getElementById("region-column"),
  channelColumn: document.getElementById("channel-column"),
  storeColumn: document.getElementById("store-column"),
  cellSiteColumn: document.getElementById("cell-site-column"),
  hourColumn: document.getElementById("hour-column"),
  technologyColumn: document.getElementById("technology-column"),
  preview: document.getElementById("preview"),
  download: document.getElementById("download"),
  statusDetail: document.getElementById("status-detail"),
  templateDetail: document.getElementById("template-detail"),
  packageId: document.getElementById("package-id"),
  files: document.getElementById("files"),
  warnings: document.getElementById("warnings"),
  requestPreview: document.getElementById("request-preview"),
};

let apiBase = "";
let template = null;
let lastRequest = null;
let lastPackageId = null;

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

function setStatus(message, state = "degraded") {
  elements.statusDetail.textContent = message;
  const existing = document.getElementById("setup-status-pill");
  if (existing) existing.remove();
  const pill = document.createElement("span");
  pill.id = "setup-status-pill";
  pill.className = `status ${state}`;
  pill.textContent =
    state === "ready" ? "Ready" : state === "failed" ? "Action required" : "Waiting";
  elements.statusDetail.prepend(pill, document.createTextNode(" "));
}

function clone(value) {
  return typeof window.structuredClone === "function"
    ? window.structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

function connectorById(mappingPack, connectorId) {
  return mappingPack.connectors.find((item) => item.connector_id === connectorId);
}

function setInput(element, value) {
  if (value !== undefined && value !== null && String(value).length) {
    element.value = String(value);
  }
}

function applyTemplate(data) {
  template = data;
  const mappingPack = data.physical_mapping_pack;
  const telecom = connectorById(mappingPack, "telecom_semantic_warehouse") || mappingPack.connectors[0];
  const network =
    connectorById(mappingPack, "network_performance_platform") || mappingPack.connectors[1] || telecom;

  setInput(elements.modelId, data.recommended_model?.model_id);
  setInput(elements.modelTimeout, data.recommended_model?.timeout_seconds);
  setInput(elements.schemaName, telecom.schema_name);
  setInput(elements.tableName, telecom.table_name);
  setInput(elements.secretName, telecom.secret_ref?.split("://", 2)[1]);
  setInput(elements.factDateColumn, telecom.fact_date_column);
  setInput(elements.periodEndColumn, telecom.period_end_column);
  setInput(elements.metricIdColumn, telecom.metric_id_column);

  const telecomMetrics = telecom.metrics || [];
  const sumMetric = telecomMetrics.find((item) => item.aggregation === "SUM");
  const ratioMetric = telecomMetrics.find((item) => item.aggregation === "RATIO");
  setInput(elements.amountColumn, sumMetric?.amount_column);
  setInput(elements.numeratorColumn, ratioMetric?.numerator_column);
  setInput(elements.denominatorColumn, ratioMetric?.denominator_column);

  setInput(elements.planColumn, telecom.dimensions?.PLAN);
  setInput(elements.marketColumn, telecom.dimensions?.MARKET);
  setInput(elements.regionColumn, telecom.dimensions?.REGION);
  setInput(elements.channelColumn, telecom.dimensions?.CHANNEL);
  setInput(elements.storeColumn, telecom.dimensions?.STORE);
  setInput(elements.cellSiteColumn, network.dimensions?.CELL_SITE);
  setInput(elements.hourColumn, network.dimensions?.HOUR);
  setInput(elements.technologyColumn, network.dimensions?.TECHNOLOGY);

  elements.templateDetail.textContent =
    `${data.domain_pack.tenant_name} · Domain ${data.domain_pack.version} · ` +
    `Mapping ${mappingPack.version} · ${data.runtime_image}`;
  elements.preview.disabled = false;
  elements.download.disabled = true;
  setStatus("Approved tenant template loaded. Review the source mapping and validate the package.", "ready");
  renderRequestSummary();
}

function physicalColumnForDimension(dimensionId) {
  const mapping = {
    PLAN: elements.planColumn.value.trim(),
    MARKET: elements.marketColumn.value.trim(),
    REGION: elements.regionColumn.value.trim(),
    CHANNEL: elements.channelColumn.value.trim(),
    STORE: elements.storeColumn.value.trim(),
    CELL_SITE: elements.cellSiteColumn.value.trim(),
    HOUR: elements.hourColumn.value.trim(),
    TECHNOLOGY: elements.technologyColumn.value.trim(),
  };
  return mapping[dimensionId];
}

function buildPhysicalMappingPack() {
  const mappingPack = clone(template.physical_mapping_pack);
  mappingPack.version = `${template.physical_mapping_pack.version}-custom`;
  const shared = {
    schema_name: elements.schemaName.value.trim(),
    table_name: elements.tableName.value.trim(),
    secret_ref: `env://${elements.secretName.value.trim()}`,
    fact_date_column: elements.factDateColumn.value.trim(),
    period_end_column: elements.periodEndColumn.value.trim(),
    metric_id_column: elements.metricIdColumn.value.trim(),
  };

  for (const connector of mappingPack.connectors) {
    Object.assign(connector, shared);
    for (const dimensionId of Object.keys(connector.dimensions)) {
      connector.dimensions[dimensionId] = physicalColumnForDimension(dimensionId);
    }
    for (const metric of connector.metrics) {
      if (metric.aggregation === "SUM") {
        metric.amount_column = elements.amountColumn.value.trim();
        metric.numerator_column = null;
        metric.denominator_column = null;
      } else if (metric.aggregation === "RATIO") {
        metric.amount_column = null;
        metric.numerator_column = elements.numeratorColumn.value.trim();
        metric.denominator_column = elements.denominatorColumn.value.trim();
      }
    }
  }
  return mappingPack;
}

function buildRequest() {
  if (!template) throw new Error("Load an approved tenant template first.");
  if (!elements.form.reportValidity()) throw new Error("Complete the highlighted setup fields.");

  return {
    project_name: elements.projectName.value.trim(),
    project_slug: elements.projectSlug.value.trim().toLowerCase(),
    api_port: Number(elements.apiPort.value),
    access_context: accessContext,
    domain_pack: template.domain_pack,
    physical_mapping_pack: buildPhysicalMappingPack(),
    model: {
      provider: "OLLAMA",
      model_id: elements.modelId.value.trim(),
      timeout_seconds: Number(elements.modelTimeout.value),
    },
  };
}

function requestSummary(request) {
  if (!request) return { status: "Template not loaded" };
  return {
    project: {
      name: request.project_name,
      slug: request.project_slug,
      tenant_id: request.domain_pack.tenant_id,
      api_port: request.api_port,
    },
    model: request.model,
    domain_pack_version: request.domain_pack.version,
    physical_mapping_version: request.physical_mapping_pack.version,
    connectors: request.physical_mapping_pack.connectors.map((connector) => ({
      connector_id: connector.connector_id,
      object: `${connector.schema_name}.${connector.table_name}`,
      secret_reference: connector.secret_ref,
      metrics: connector.metrics.map((metric) => metric.metric_id),
    })),
  };
}

function renderRequestSummary() {
  try {
    elements.requestPreview.textContent = JSON.stringify(requestSummary(buildRequest()), null, 2);
  } catch (error) {
    elements.requestPreview.textContent = error.message;
  }
}

function renderPreview(data) {
  lastPackageId = data.package_id;
  elements.packageId.textContent = data.package_id;
  elements.files.textContent = "";
  for (const file of data.files) {
    const row = document.createElement("div");
    row.className = "file-row";
    const name = document.createElement("span");
    name.textContent = file.path;
    const size = document.createElement("span");
    size.textContent = `${file.size_bytes} bytes`;
    row.append(name, size);
    elements.files.appendChild(row);
  }
  elements.warnings.textContent = "";
  for (const warning of data.warnings || []) {
    const node = document.createElement("div");
    node.className = "warning";
    node.textContent = warning;
    elements.warnings.appendChild(node);
  }
  if (!(data.warnings || []).length) elements.warnings.textContent = "None.";
  elements.download.disabled = false;
  setStatus("Package contract validated. Download is enabled.", "ready");
}

async function parseError(response) {
  const data = await response.json().catch(() => ({}));
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return `HTTP ${response.status}`;
}

async function connect() {
  apiBase = normalizeBaseUrl(elements.apiBase.value);
  if (!apiBase) {
    setStatus("Enter the forwarded Talk2Data API URL.", "failed");
    return;
  }

  elements.connect.disabled = true;
  elements.preview.disabled = true;
  elements.download.disabled = true;
  setStatus(`Checking ${apiBase}…`, "degraded");
  try {
    const readiness = await fetch(`${apiBase}/health/ready`, {
      headers: { Accept: "application/json" },
    });
    if (!readiness.ok) throw new Error(await parseError(readiness));
    const health = await readiness.json();
    if (health.status !== "ready") throw new Error(`Runtime readiness is ${health.status}.`);

    const response = await fetch(`${apiBase}/v1/runtime-packages/template`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ access_context: accessContext }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    const data = await response.json();
    window.localStorage.setItem("talk2data.apiBase", apiBase);
    applyTemplate(data);
  } catch (error) {
    template = null;
    elements.templateDetail.textContent = "—";
    setStatus(`${error.message} Confirm the runtime URL, CORS, and API version.`, "failed");
  } finally {
    elements.connect.disabled = false;
  }
}

async function preview(event) {
  event.preventDefault();
  try {
    const request = buildRequest();
    lastRequest = request;
    lastPackageId = null;
    elements.preview.disabled = true;
    elements.download.disabled = true;
    setStatus("Validating semantic, mapping, policy, and package contracts…", "degraded");
    renderRequestSummary();

    const response = await fetch(`${apiBase}/v1/runtime-packages/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    });
    if (!response.ok) throw new Error(await parseError(response));
    renderPreview(await response.json());
  } catch (error) {
    lastRequest = null;
    elements.packageId.textContent = "—";
    elements.files.textContent = "—";
    elements.warnings.textContent = error.message;
    setStatus(error.message, "failed");
  } finally {
    elements.preview.disabled = !template;
  }
}

async function download() {
  if (!lastRequest || !lastPackageId) {
    setStatus("Validate the package before downloading it.", "failed");
    return;
  }
  elements.download.disabled = true;
  setStatus("Building deterministic ZIP package…", "degraded");
  try {
    const response = await fetch(`${apiBase}/v1/runtime-packages/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/zip" },
      body: JSON.stringify(lastRequest),
    });
    if (!response.ok) throw new Error(await parseError(response));
    const packageId = response.headers.get("x-talk2data-package-id");
    if (packageId !== lastPackageId) throw new Error("Package receipt changed between preview and download.");

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${lastRequest.project_slug}-talk2data-runtime.zip`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setStatus("Package downloaded. Copy `.env.example` to `.env` and add the read-only DSN.", "ready");
  } catch (error) {
    setStatus(error.message, "failed");
  } finally {
    elements.download.disabled = !lastRequest;
  }
}

elements.connect.addEventListener("click", () => void connect());
elements.form.addEventListener("submit", (event) => void preview(event));
elements.download.addEventListener("click", () => void download());
for (const input of elements.form.querySelectorAll("input")) {
  input.addEventListener("input", () => {
    lastRequest = null;
    lastPackageId = null;
    elements.download.disabled = true;
    renderRequestSummary();
  });
}

apiBase = configuredBaseUrl();
elements.apiBase.value = apiBase;
if (apiBase) {
  void connect();
} else {
  setStatus("Launch the Talk2Data runtime and enter its forwarded API URL.", "degraded");
}
