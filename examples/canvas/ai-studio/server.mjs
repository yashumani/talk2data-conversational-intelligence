import { createReadStream } from "node:fs";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { runPreviewModel } from "./model.mjs";

const directory = dirname(fileURLToPath(import.meta.url));
const host = "127.0.0.1";
const port = Number(process.env.PORT || 4178);
const maximumRequestBytes = 32 * 1024;
const maximumResponseBytes = 256 * 1024;
const deadlineMilliseconds = 20_000;
const rates = new Map();
let inFlight = 0;

function securityHeaders(contentType) {
  return {
    "cache-control": "no-store",
    "content-type": contentType,
    "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
  };
}

function reply(response, status, body, contentType = "application/json; charset=utf-8") {
  const payload = Buffer.from(typeof body === "string" ? body : JSON.stringify(body));
  if (payload.length > maximumResponseBytes) {
    response.writeHead(502, securityHeaders("application/json; charset=utf-8"));
    response.end(JSON.stringify({ error: "preview response exceeded the configured limit" }));
    return;
  }
  response.writeHead(status, { ...securityHeaders(contentType), "content-length": payload.length });
  response.end(payload);
}

function identity(request) {
  return request.socket.remoteAddress || "local";
}

function allowedOrigins(request) {
  const authority = request.headers.host || "";
  const hostname = authority.replace(/^\[/, "").replace(/\].*$/, "").split(":")[0];
  return new Set(["127.0.0.1", "localhost"]).has(hostname)
    && request.headers.origin === `http://${authority}`;
}

function admitted(request) {
  const now = Date.now();
  for (const [key, value] of rates) if (value.reset <= now) rates.delete(key);
  while (rates.size >= 1024) rates.delete(rates.keys().next().value);
  const key = identity(request);
  const current = rates.get(key);
  if (!current || current.reset <= now) { rates.set(key, { count: 1, reset: now + 60_000 }); return true; }
  current.count += 1;
  return current.count <= 60;
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maximumRequestBytes) throw Object.assign(new Error("request too large"), { status: 413 });
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString("utf8")); }
  catch { throw Object.assign(new Error("request must be valid JSON"), { status: 400 }); }
}

export function createPreviewServer() {
  return createServer(async (request, response) => {
    let target;
    try { target = new URL(request.url, `http://${request.headers.host || `${host}:${port}`}`); }
    catch { reply(response, 400, { error: "invalid request target" }); return; }
    if (target.origin !== `http://${request.headers.host}` || !target.pathname.startsWith("/")) {
      reply(response, 400, { error: "invalid request target" }); return;
    }
    if (request.method === "GET" && ["/", "/index.html", "/client.mjs"].includes(target.pathname)) {
      const file = target.pathname === "/client.mjs" ? "client.mjs" : "index.html";
      response.writeHead(200, securityHeaders(file.endsWith(".mjs") ? "text/javascript; charset=utf-8" : "text/html; charset=utf-8"));
      createReadStream(join(directory, file)).pipe(response);
      return;
    }
    if (request.method !== "POST" || target.pathname !== "/api/preview") {
      reply(response, 404, { error: "not found" }); return;
    }
    if (!allowedOrigins(request)) { reply(response, 403, { error: "origin denied" }); return; }
    if (!admitted(request)) { reply(response, 429, { error: "rate limit exceeded" }); return; }
    if (inFlight >= 4) { reply(response, 503, { error: "preview capacity reached" }); return; }
    inFlight += 1;
    const disconnected = new AbortController();
    request.once("aborted", () => disconnected.abort(new Error("client disconnected")));
    response.once("close", () => { if (!response.writableEnded) disconnected.abort(new Error("client disconnected")); });
    const deadline = AbortSignal.timeout(deadlineMilliseconds);
    const signal = AbortSignal.any([disconnected.signal, deadline]);
    try {
      const body = await readJson(request);
      if (typeof body.prompt !== "string" || body.prompt.trim().length < 2 || body.prompt.length > 4_000) {
        reply(response, 422, { error: "prompt must contain 2–4000 characters" }); return;
      }
      const output = await runPreviewModel(body.prompt, { signal });
      reply(response, 200, { output, model: "deterministic-local-preview", external_request: false });
    } catch (error) {
      if (!response.headersSent) reply(response, error?.status || (deadline.aborted ? 504 : 400), { error: deadline.aborted ? "preview deadline exceeded" : String(error?.message || "preview failed") });
    } finally { inFlight -= 1; }
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  createPreviewServer().listen(port, host, () => console.log(`AI Studio preview: http://${host}:${port}`));
}
