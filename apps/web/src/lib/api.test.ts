import { strict as assert } from "node:assert";
import { afterEach, test } from "vitest";
import { api, ApiError } from "./api.ts";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test("query requests carry source revision, not client-controlled roles or warehouse config", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(input, "/v1/demo/csv/chat");
    assert.equal(new Headers(init?.headers).get("X-Demo-Session"), "opaque-token");
    assert.equal(init?.cache, "no-store");
    assert.deepEqual(JSON.parse(String(init?.body)), {
      question: "Activations yesterday?", as_of: "2026-08-01T12:00:00Z",
      source_fingerprint: "a".repeat(64),
    });
    return Response.json({ status: "ANSWERED" });
  };
  assert.equal((await api.ask("opaque-token", "Activations yesterday?", "2026-08-01", "a".repeat(64))).status,
    "ANSWERED");
});

test("upload sends raw CSV, not a path or warehouse reference", async () => {
  const file = new File(["date,region,channel,activations"], "demo.csv");
  globalThis.fetch = async (input, init) => {
    assert.equal(input, "/v1/demo/csv/upload");
    assert.equal(new Headers(init?.headers).get("Content-Type"), "text/csv");
    assert.equal(init?.body, file);
    return Response.json({});
  };
  await api.upload("token", file);
});

test("session creation, state refresh, and clear use separate endpoints", async () => {
  const called: string[] = [];
  globalThis.fetch = async input => {
    called.push(String(input));
    return String(input).endsWith("/clear") ? new Response(null, { status: 204 }) : Response.json({});
  };
  await api.createSession();
  await api.state("token");
  assert.equal(await api.clear("token"), undefined);
  assert.deepEqual(called, [
    "/v1/demo/csv/sessions", "/v1/demo/csv/state", "/v1/demo/csv/clear",
  ]);
});

test("expired sessions preserve status and server explanation", async () => {
  globalThis.fetch = async () => Response.json({ detail: "Session expired." }, { status: 401 });
  await assert.rejects(api.state("expired"), error =>
    error instanceof ApiError && error.status === 401 && error.message === "Session expired.");
});

test("disabled demo and structured validation errors are readable", async () => {
  globalThis.fetch = async () => new Response("<html>Not found</html>", { status: 404 });
  await assert.rejects(api.state("token"), /disabled or the backend/);
  globalThis.fetch = async () => Response.json({ detail: [{ msg: "field invalid" }] }, { status: 422 });
  await assert.rejects(api.state("token"), /request was invalid/);
});

test("network failures are surfaced and never retried against another source", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error("Network unavailable"); };
  await assert.rejects(api.state("token"), /Network unavailable/);
  assert.equal(calls, 1);
});


test("definition endpoints send review revisions and keep route identifiers encoded", async () => {
  const calls: { path: string; body: unknown }[] = [];
  globalThis.fetch = async (input, init) => {
    assert.equal(new Headers(init?.headers).get("X-Demo-Session"), "token");
    assert.equal(init?.method, "POST");
    calls.push({ path: String(input), body: init?.body ? JSON.parse(String(init.body)) : null });
    return String(input).endsWith("/revoke") ? new Response(null, { status: 204 }) : Response.json({});
  };
  const edit = { base_snapshot_id: "b".repeat(64), kind: "METRIC" as const, definition_id: "MOBILE_ACTIVATIONS",
    name: "Activations", definition: "Completed connections", owner: "Sales", aliases: [], reason: "Clarify" };
  await api.createDraft("token", edit);
  await api.reviewDraft("token", { draft_id: "draft/1", revision: 3, status: "APPROVED", edit, review_note: "Checked" }, "publish", "Release");
  await api.revokeDefinition("token", "snapshot/2", 7, "Withdraw");
  await api.rerun("token", "run/1");
  await api.ask("token", "Activations?", "2026-08-01", "a".repeat(64), edit.base_snapshot_id);
  assert.deepEqual(calls.slice(0, 4), [
    { path: "/v1/demo/csv/definitions/drafts", body: edit },
    { path: "/v1/demo/csv/definitions/drafts/draft%2F1/publish", body: { expected_revision: 3, note: "Release" } },
    { path: "/v1/demo/csv/definitions/snapshots/snapshot%2F2/revoke", body: { expected_revision: 7, note: "Withdraw" } },
    { path: "/v1/demo/csv/history/run%2F1/rerun", body: null },
  ]);
  assert.equal((calls[4].body as { definition_snapshot_id: string }).definition_snapshot_id, edit.base_snapshot_id);
});
