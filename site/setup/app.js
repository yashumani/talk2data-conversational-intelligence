"use strict";

const RUNTIME_IMAGE = "ghcr.io/yashumani/talk2data-conversational-intelligence:main";
const CODESPACES_URL = "https://codespaces.new/yashumani/talk2data-conversational-intelligence?ref=main&quickstart=1";
const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;
const SECRET_NAME = /^[A-Z_][A-Z0-9_]*$/;
const PROJECT_SLUG = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const MODEL_NAME = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/;
const encoder = new TextEncoder();

let currentStep = 1;
let domainTemplatePromise;

const byId = (id) => document.getElementById(id);
const panels = [...document.querySelectorAll("[data-step-panel]")];
const steps = [...document.querySelectorAll("[data-step-target]")];

function initialize() {
  byId("effectiveDate").value = new Date().toISOString().slice(0, 10);
  steps.forEach((step) => step.addEventListener("click", () => showStep(Number(step.dataset.stepTarget))));
  byId("backButton").addEventListener("click", () => showStep(currentStep - 1));
  byId("nextButton").addEventListener("click", () => {
    if (validateStep(currentStep)) showStep(currentStep + 1);
  });
  byId("validateButton").addEventListener("click", validateAndRender);
  byId("downloadButton").addEventListener("click", downloadPackage);
  byId("displayName").addEventListener("input", suggestSlug);
  byId("builder").addEventListener("input", () => {
    if (currentStep === 5) renderSummary(collectConfig());
    setValidation("Configuration changed. Run validation again.", "neutral");
  });
  showStep(1);
  renderSummary(collectConfig());
}

function suggestSlug(event) {
  const slug = event.target.value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
  if (!byId("projectSlug").dataset.edited) byId("projectSlug").value = slug || "talk2data-tenant";
}
byId("projectSlug").addEventListener("input", () => { byId("projectSlug").dataset.edited = "true"; });

function showStep(step) {
  currentStep = Math.max(1, Math.min(5, step));
  panels.forEach((panel) => panel.classList.toggle("active", Number(panel.dataset.stepPanel) === currentStep));
  steps.forEach((item) => item.classList.toggle("active", Number(item.dataset.stepTarget) === currentStep));
  byId("backButton").disabled = currentStep === 1;
  byId("nextButton").hidden = currentStep === 5;
  byId("stepStatus").textContent = `Step ${currentStep} of 5`;
  if (currentStep === 5) renderSummary(collectConfig());
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function validateStep(step) {
  const panel = document.querySelector(`[data-step-panel="${step}"]`);
  const fields = [...panel.querySelectorAll("input[required]")];
  let valid = true;
  fields.forEach((field) => {
    field.setCustomValidity("");
    if (!field.value.trim()) {
      field.setCustomValidity("This value is required.");
      valid = false;
    }
    if (!field.reportValidity()) valid = false;
  });
  return valid;
}

function collectConfig() {
  return {
    displayName: byId("displayName").value.trim(),
    projectSlug: byId("projectSlug").value.trim().toLowerCase(),
    tenantId: byId("tenantId").value.trim(),
    mappingVersion: byId("mappingVersion").value.trim(),
    effectiveDate: byId("effectiveDate").value,
    schemaName: byId("schemaName").value.trim(),
    tableName: byId("tableName").value.trim(),
    secretName: byId("secretName").value.trim().toUpperCase(),
    factDateColumn: byId("factDateColumn").value.trim(),
    periodEndColumn: byId("periodEndColumn").value.trim(),
    metricIdColumn: byId("metricIdColumn").value.trim(),
    amountColumn: byId("amountColumn").value.trim(),
    numeratorColumn: byId("numeratorColumn").value.trim(),
    denominatorColumn: byId("denominatorColumn").value.trim(),
    dimensions: {
      PLAN: byId("planColumn").value.trim(),
      MARKET: byId("marketColumn").value.trim(),
      REGION: byId("regionColumn").value.trim(),
      CHANNEL: byId("channelColumn").value.trim(),
      STORE: byId("storeColumn").value.trim(),
      CELL_SITE: byId("cellSiteColumn").value.trim(),
      HOUR: byId("hourColumn").value.trim(),
      TECHNOLOGY: byId("technologyColumn").value.trim(),
    },
    sourceValues: {
      POSTPAID_CHURN: byId("churnSourceValue").value.trim(),
      MOBILE_ACTIVATIONS: byId("activationSourceValue").value.trim(),
      NETWORK_CONGESTION: byId("congestionSourceValue").value.trim(),
    },
    ollamaModel: byId("ollamaModel").value.trim(),
    apiPort: Number(byId("apiPort").value),
    maximumRows: Number(byId("maximumRows").value),
    queryTimeout: Number(byId("queryTimeout").value),
    includeCodespaces: byId("includeCodespaces").checked,
  };
}

function validateConfig(config) {
  const errors = [];
  if (!PROJECT_SLUG.test(config.projectSlug)) errors.push("Project slug must use lowercase letters, numbers, and hyphens.");
  if (!config.displayName) errors.push("Display name is required.");
  if (!config.mappingVersion) errors.push("Mapping version is required.");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(config.effectiveDate)) errors.push("Effective date is required.");
  if (!SECRET_NAME.test(config.secretName)) errors.push("Secret variable must be an uppercase environment-variable name.");
  if (!MODEL_NAME.test(config.ollamaModel)) errors.push("Ollama model name contains unsupported characters.");
  if (!Number.isInteger(config.apiPort) || config.apiPort < 1024 || config.apiPort > 65535) errors.push("API port must be between 1024 and 65535.");
  if (!Number.isInteger(config.maximumRows) || config.maximumRows < 1 || config.maximumRows > 10000) errors.push("Maximum rows must be between 1 and 10000.");
  if (!Number.isInteger(config.queryTimeout) || config.queryTimeout < 1 || config.queryTimeout > 1800) errors.push("Query timeout must be between 1 and 1800 seconds.");

  const identifiers = {
    schema: config.schemaName,
    table: config.tableName,
    fact_date: config.factDateColumn,
    period_end: config.periodEndColumn,
    metric_id: config.metricIdColumn,
    amount: config.amountColumn,
    numerator: config.numeratorColumn,
    denominator: config.denominatorColumn,
    ...config.dimensions,
  };
  Object.entries(identifiers).forEach(([name, value]) => {
    if (!IDENTIFIER.test(value)) errors.push(`${name} must be a simple SQL identifier.`);
  });
  Object.entries(config.sourceValues).forEach(([metric, value]) => {
    if (!value || value.length > 256) errors.push(`${metric} needs a physical discriminator value.`);
  });
  const telecomDimensions = ["PLAN", "MARKET", "REGION", "CHANNEL", "STORE"].map((id) => config.dimensions[id]);
  const networkDimensions = ["MARKET", "CELL_SITE", "HOUR", "TECHNOLOGY"].map((id) => config.dimensions[id]);
  if (new Set(telecomDimensions).size !== telecomDimensions.length) errors.push("Telecom semantic dimensions must map to distinct physical columns.");
  if (new Set(networkDimensions).size !== networkDimensions.length) errors.push("Network semantic dimensions must map to distinct physical columns.");
  return errors;
}

function validateAndRender() {
  const config = collectConfig();
  const errors = validateConfig(config);
  renderSummary(config);
  if (errors.length) {
    setValidation(`<strong>Configuration needs attention.</strong><br>${errors.map(escapeHtml).join("<br>")}`, "bad");
    return false;
  }
  setValidation("Configuration is structurally valid. The generated package will still validate the real schema and source coverage when it starts.", "good");
  return true;
}

function renderSummary(config) {
  const items = [
    ["Project", config.projectSlug || "—"],
    ["Tenant", config.tenantId || "—"],
    ["Source", `${config.schemaName || "—"}.${config.tableName || "—"}`],
    ["Local model", config.ollamaModel || "—"],
    ["API", `localhost:${config.apiPort || "—"}`],
    ["Secret ref", `env://${config.secretName || "—"}`],
    ["Metrics", "3 governed metrics"],
    ["Runtime", RUNTIME_IMAGE.split("/").pop()],
  ];
  byId("summary").innerHTML = items.map(([label, value]) => `<div class="summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  byId("fileList").innerHTML = packagePaths(config).map((path) => `<li>${escapeHtml(path)}</li>`).join("");
}

function packagePaths(config) {
  const paths = [
    ".env.example",
    ".github/workflows/validate.yml",
    "README.md",
    "checksums.json",
    `config/domain-packs/${config.tenantId}.yaml`,
    `config/physical-mappings/${config.tenantId}.yaml`,
    "config/talk2data.yaml",
    "docker-compose.yml",
    "scripts/start.ps1",
    "scripts/start.sh",
  ];
  if (config.includeCodespaces) paths.push(".devcontainer/devcontainer.json");
  return paths.sort();
}

async function downloadPackage() {
  if (!validateAndRender()) return;
  const button = byId("downloadButton");
  button.disabled = true;
  button.textContent = "Building package…";
  try {
    const config = collectConfig();
    const files = await buildFiles(config);
    const checksums = {};
    for (const path of Object.keys(files).sort()) checksums[path] = await sha256(files[path]);
    files["checksums.json"] = JSON.stringify(checksums, null, 2) + "\n";
    const zip = makeZip(files);
    const packageHash = await sha256Bytes(zip);
    const blob = new Blob([zip], { type: "application/zip" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${config.projectSlug}-talk2data-runtime.zip`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setValidation(`Package generated. SHA-256: <code>${packageHash}</code>`, "good");
  } catch (error) {
    console.error(error);
    setValidation(`Package generation failed: ${escapeHtml(error.message || String(error))}`, "bad");
  } finally {
    button.disabled = false;
    button.textContent = "Download runtime package";
  }
}

async function buildFiles(config) {
  const domainPack = await loadDomainTemplate();
  const files = {
    "README.md": readme(config),
    ".env.example": environmentExample(config),
    "docker-compose.yml": dockerCompose(config),
    [`config/domain-packs/${config.tenantId}.yaml`]: domainPack,
    [`config/physical-mappings/${config.tenantId}.yaml`]: physicalMapping(config),
    "config/talk2data.yaml": talk2dataManifest(config),
    "scripts/start.sh": startShell(),
    "scripts/start.ps1": startPowerShell(),
    ".github/workflows/validate.yml": validationWorkflow(config),
  };
  if (config.includeCodespaces) files[".devcontainer/devcontainer.json"] = devcontainer();
  return files;
}

function loadDomainTemplate() {
  if (!domainTemplatePromise) {
    domainTemplatePromise = fetch("./templates/telecom-domain-pack.yaml")
      .then((response) => {
        if (!response.ok) throw new Error("The starter Domain Pack could not be loaded.");
        return response.text();
      });
  }
  return domainTemplatePromise;
}

function physicalMapping(c) {
  const d = c.dimensions;
  return `tenant_id: ${yamlScalar(c.tenantId)}
version: ${yamlScalar(c.mappingVersion)}
status: APPROVED
effective_from: ${yamlScalar(`${c.effectiveDate}T00:00:00Z`)}
connectors:
  - connector_id: telecom_semantic_warehouse
    connector_type: POSTGRESQL
    schema_name: ${c.schemaName}
    table_name: ${c.tableName}
    secret_ref: env://${c.secretName}
    fact_date_column: ${c.factDateColumn}
    period_end_column: ${c.periodEndColumn}
    metric_id_column: ${c.metricIdColumn}
    dimensions:
      PLAN: ${d.PLAN}
      MARKET: ${d.MARKET}
      REGION: ${d.REGION}
      CHANNEL: ${d.CHANNEL}
      STORE: ${d.STORE}
    scope_value_allowlists:
      REGION: [NORTHEAST, SOUTHEAST, CENTRAL, WEST]
    scope_value_mappings:
      REGION:
        NORTH_AMERICA: [NORTHEAST, SOUTHEAST, CENTRAL, WEST]
        NORTHEAST: [NORTHEAST]
        SOUTHEAST: [SOUTHEAST]
        CENTRAL: [CENTRAL]
        WEST: [WEST]
    maximum_rows: ${c.maximumRows}
    query_timeout_seconds: ${c.queryTimeout}
    expected_refresh: Source-managed certified reporting periods
    metrics:
      - metric_id: POSTPAID_CHURN
        source_value: ${yamlScalar(c.sourceValues.POSTPAID_CHURN)}
        aggregation: RATIO
        numerator_column: ${c.numeratorColumn}
        denominator_column: ${c.denominatorColumn}
        allowed_dimensions: [PLAN, MARKET, REGION, CHANNEL]
      - metric_id: MOBILE_ACTIVATIONS
        source_value: ${yamlScalar(c.sourceValues.MOBILE_ACTIVATIONS)}
        aggregation: SUM
        amount_column: ${c.amountColumn}
        allowed_dimensions: [STORE, MARKET, REGION, CHANNEL, PLAN]

  - connector_id: network_performance_platform
    connector_type: POSTGRESQL
    schema_name: ${c.schemaName}
    table_name: ${c.tableName}
    secret_ref: env://${c.secretName}
    fact_date_column: ${c.factDateColumn}
    period_end_column: ${c.periodEndColumn}
    metric_id_column: ${c.metricIdColumn}
    dimensions:
      MARKET: ${d.MARKET}
      CELL_SITE: ${d.CELL_SITE}
      HOUR: ${d.HOUR}
      TECHNOLOGY: ${d.TECHNOLOGY}
    scope_value_allowlists: {}
    scope_value_mappings: {}
    maximum_rows: ${c.maximumRows}
    query_timeout_seconds: ${c.queryTimeout}
    expected_refresh: Source-managed certified reporting periods
    metrics:
      - metric_id: NETWORK_CONGESTION
        source_value: ${yamlScalar(c.sourceValues.NETWORK_CONGESTION)}
        aggregation: RATIO
        numerator_column: ${c.numeratorColumn}
        denominator_column: ${c.denominatorColumn}
        allowed_dimensions: [MARKET, CELL_SITE, HOUR, TECHNOLOGY]
`;
}

function talk2dataManifest(c) {
  return `project_slug: ${yamlScalar(c.projectSlug)}
display_name: ${yamlScalar(c.displayName)}
tenant_id: ${yamlScalar(c.tenantId)}
runtime_image: ${yamlScalar(RUNTIME_IMAGE)}
ollama_model: ${yamlScalar(c.ollamaModel)}
api_port: ${c.apiPort}
connectors:
  - network_performance_platform
  - telecom_semantic_warehouse
mapping_version: ${yamlScalar(c.mappingVersion)}
source_repository: https://github.com/yashumani/talk2data-conversational-intelligence
`;
}

function environmentExample(c) {
  return `# Copy this file to .env. Never commit .env.
T2D_PROJECT_SLUG=${c.projectSlug}
T2D_API_PORT=${c.apiPort}
T2D_RUNTIME_IMAGE=${RUNTIME_IMAGE}
T2D_OLLAMA_MODEL=${c.ollamaModel}

# Set the real database connection locally.
${c.secretName}=
`;
}

function dockerCompose(c) {
  return `name: \${T2D_PROJECT_SLUG:-${c.projectSlug}}

services:
  ollama:
    image: ollama/ollama:latest
    restart: unless-stopped
    volumes:
      - ollama_models:/root/.ollama
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 10s
      timeout: 5s
      retries: 30

  ollama-pull:
    image: ollama/ollama:latest
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      OLLAMA_HOST: http://ollama:11434
      T2D_OLLAMA_MODEL: "\${T2D_OLLAMA_MODEL:-${c.ollamaModel}}"
    entrypoint: ["/bin/sh", "-c"]
    command: ["ollama pull \${T2D_OLLAMA_MODEL}"]
    restart: "no"

  talk2data:
    image: "\${T2D_RUNTIME_IMAGE:-${RUNTIME_IMAGE}}"
    pull_policy: always
    depends_on:
      ollama-pull:
        condition: service_completed_successfully
    restart: unless-stopped
    ports:
      - "\${T2D_API_PORT:-${c.apiPort}}:8000"
    environment:
      T2D_ENVIRONMENT: tenant
      T2D_DEFAULT_TENANT_ID: ${c.tenantId}
      T2D_DATA_BACKEND: postgresql
      T2D_DATABASE_PATH: /state/talk2data.db
      T2D_DOMAIN_PACK_DIRECTORY: /config/domain-packs
      T2D_PHYSICAL_MAPPING_DIRECTORY: /config/physical-mappings
      T2D_OLLAMA_ENABLED: "true"
      T2D_OLLAMA_REQUIRED: "false"
      T2D_OLLAMA_BASE_URL: http://ollama:11434
      T2D_OLLAMA_MODEL: "\${T2D_OLLAMA_MODEL:-${c.ollamaModel}}"
      ${c.secretName}: "\${${c.secretName}:?Set ${c.secretName} in .env}"
    volumes:
      - ./config:/config:ro
      - talk2data_state:/state

volumes:
  ollama_models:
  talk2data_state:
`;
}

function readme(c) {
  return `# ${c.displayName}

This generated package configures the stable Talk2Data runtime for tenant \`${c.tenantId}\`.

## Start

1. Install Docker Desktop or Docker Engine with Compose.
2. Copy \`.env.example\` to \`.env\`.
3. Set \`${c.secretName}\` in \`.env\`.
4. Run \`docker compose up -d\`.
5. Open http://localhost:${c.apiPort}/demo.
6. Inspect http://localhost:${c.apiPort}/health/ready and /docs.

No database password, token, or production data was included in this package.
Ollama interprets language; governed connectors calculate and verify numerical answers.

Codespaces evaluation: ${CODESPACES_URL}
`;
}

function startShell() {
  return `#!/usr/bin/env sh
set -eu
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Set the required connector secret, then run again."
  exit 1
fi
docker compose up -d
docker compose ps
`;
}

function startPowerShell() {
  return `$ErrorActionPreference = "Stop"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Set the required connector secret, then run again."
    exit 1
}
docker compose up -d
docker compose ps
`;
}

function devcontainer() {
  return JSON.stringify({
    name: "Talk2Data tenant runtime",
    image: "mcr.microsoft.com/devcontainers/base:ubuntu",
    features: { "ghcr.io/devcontainers/features/docker-in-docker:2": {} },
    forwardPorts: [8000],
    portsAttributes: { "8000": { label: "Talk2Data", onAutoForward: "openBrowser" } },
    postCreateCommand: "cp -n .env.example .env || true",
  }, null, 2) + "\n";
}

function validationWorkflow(c) {
  return `name: Validate Talk2Data tenant package

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  package:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verify checksums
        run: |
          python - <<'PY'
          import hashlib, json
          from pathlib import Path
          expected = json.loads(Path("checksums.json").read_text())
          actual = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in expected}
          if actual != expected:
              raise SystemExit("Package checksum verification failed.")
          PY
      - name: Validate Docker Compose
        run: |
          export ${c.secretName}=placeholder
          docker compose config --quiet
`;
}

function yamlScalar(value) {
  return JSON.stringify(String(value));
}

async function sha256(text) {
  return sha256Bytes(encoder.encode(text));
}

async function sha256Bytes(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function makeZip(files) {
  const entries = Object.keys(files).sort().map((name) => {
    const nameBytes = encoder.encode(name);
    const data = encoder.encode(files[name]);
    return { name, nameBytes, data, crc: crc32(data) };
  });
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  entries.forEach((entry) => {
    const local = new Uint8Array(30 + entry.nameBytes.length + entry.data.length);
    const view = new DataView(local.buffer);
    view.setUint32(0, 0x04034b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 0, true);
    view.setUint16(8, 0, true);
    view.setUint16(10, 0, true);
    view.setUint16(12, 0x21, true);
    view.setUint32(14, entry.crc, true);
    view.setUint32(18, entry.data.length, true);
    view.setUint32(22, entry.data.length, true);
    view.setUint16(26, entry.nameBytes.length, true);
    view.setUint16(28, 0, true);
    local.set(entry.nameBytes, 30);
    local.set(entry.data, 30 + entry.nameBytes.length);
    localParts.push(local);

    const central = new Uint8Array(46 + entry.nameBytes.length);
    const centralView = new DataView(central.buffer);
    centralView.setUint32(0, 0x02014b50, true);
    centralView.setUint16(4, 20, true);
    centralView.setUint16(6, 20, true);
    centralView.setUint16(8, 0, true);
    centralView.setUint16(10, 0, true);
    centralView.setUint16(12, 0, true);
    centralView.setUint16(14, 0x21, true);
    centralView.setUint32(16, entry.crc, true);
    centralView.setUint32(20, entry.data.length, true);
    centralView.setUint32(24, entry.data.length, true);
    centralView.setUint16(28, entry.nameBytes.length, true);
    centralView.setUint16(30, 0, true);
    centralView.setUint16(32, 0, true);
    centralView.setUint16(34, 0, true);
    centralView.setUint16(36, 0, true);
    centralView.setUint32(38, nameEndsExecutable(entry.name) ? 0x81ed0000 : 0x81a40000, true);
    centralView.setUint32(42, offset, true);
    central.set(entry.nameBytes, 46);
    centralParts.push(central);
    offset += local.length;
  });
  const centralSize = centralParts.reduce((sum, item) => sum + item.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(4, 0, true);
  endView.setUint16(6, 0, true);
  endView.setUint16(8, entries.length, true);
  endView.setUint16(10, entries.length, true);
  endView.setUint32(12, centralSize, true);
  endView.setUint32(16, offset, true);
  endView.setUint16(20, 0, true);
  return concatenate([...localParts, ...centralParts, end]);
}

function concatenate(parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const output = new Uint8Array(total);
  let offset = 0;
  parts.forEach((part) => { output.set(part, offset); offset += part.length; });
  return output;
}

function nameEndsExecutable(name) {
  return name.endsWith(".sh") || name.endsWith(".ps1");
}

const crcTable = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = (c & 1) ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  bytes.forEach((byte) => { crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8); });
  return (crc ^ 0xffffffff) >>> 0;
}

function setValidation(message, state) {
  const target = byId("validation");
  target.className = `validation ${state}`;
  target.innerHTML = message;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char]));
}

initialize();
