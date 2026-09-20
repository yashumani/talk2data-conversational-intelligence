import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";
import { createPreviewServer } from "./server.mjs";

async function running() {
  const server = createPreviewServer().listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  return { server, base: `http://127.0.0.1:${address.port}` };
}

test("serves HTML with an external same-origin module", async (t) => {
  const { server, base } = await running(); t.after(() => server.close());
  const response = await fetch(base); const html = await response.text();
  assert.equal(response.status, 200); assert.match(html, /src="\/client\.mjs"/); assert.doesNotMatch(html, /api[_-]?key/i);
});

test("serves the client as JavaScript", async (t) => {
  const { server, base } = await running(); t.after(() => server.close());
  const response = await fetch(`${base}/client.mjs`); assert.match(response.headers.get("content-type"), /javascript/);
});

test("runs the no-key deterministic preview", async (t) => {
  const { server, base } = await running(); t.after(() => server.close());
  const response = await fetch(`${base}/api/preview`, { method: "POST", headers: { origin: base, "content-type": "application/json" }, body: JSON.stringify({ prompt: "Explain the boundary" }) });
  const body = await response.json(); assert.equal(response.status, 200); assert.equal(body.external_request, false); assert.equal(body.model, "deterministic-local-preview");
});

test("rejects a missing origin", async (t) => {
  const { server, base } = await running(); t.after(() => server.close());
  const response = await fetch(`${base}/api/preview`, { method: "POST", body: JSON.stringify({ prompt: "hello" }) }); assert.equal(response.status, 403);
});

test("rejects an unlisted origin", async (t) => {
  const { server, base } = await running(); t.after(() => server.close());
  const response = await fetch(`${base}/api/preview`, { method: "POST", headers: { origin: "https://example.com" }, body: JSON.stringify({ prompt: "hello" }) }); assert.equal(response.status, 403);
});

test("rejects invalid prompts", async (t) => {
  const { server, base } = await running(); t.after(() => server.close());
  const response = await fetch(`${base}/api/preview`, { method: "POST", headers: { origin: base, "content-type": "application/json" }, body: JSON.stringify({ prompt: "" }) }); assert.equal(response.status, 422);
});

test("rejects oversized bodies", async (t) => {
  const { server, base } = await running(); t.after(() => server.close());
  const response = await fetch(`${base}/api/preview`, { method: "POST", headers: { origin: base }, body: JSON.stringify({ prompt: "x".repeat(40_000) }) }); assert.equal(response.status, 413);
});

test("returns security headers and no-store", async (t) => {
  const { server, base } = await running(); t.after(() => server.close());
  const response = await fetch(base); assert.equal(response.headers.get("cache-control"), "no-store"); assert.match(response.headers.get("content-security-policy"), /script-src 'self'/);
});
