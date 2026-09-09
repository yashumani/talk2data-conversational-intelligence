import { afterEach, expect, it, vi } from "vitest";
import { readEvents, runApi, terminal, type RunEvent, type RunSnapshot } from "./runs";

const request = { client_request_id: "request", conversation_id: "conversation", expected_revision: 0,
  question: "Mobile activations last month?", as_of: "2026-08-01T12:00:00Z",
  source_fingerprint: "a".repeat(64), definition_snapshot_id: "b".repeat(64) };
const initial: RunSnapshot = { run_id: "run", request, source_binding: request.source_fingerprint,
  status: "RUNNING", sequence: 0, progress: null, result: null, error_code: null, message: "Working" };
const final = { ...initial, status: "COMPLETED", sequence: 2, message: "Complete" };
const event = (sequence: number, status = "RUNNING"): RunEvent => ({ run_id: "run", sequence, status, progress: null });
function frame(value: RunEvent) { return "id: run:" + value.sequence + "\nevent: progress\ndata: " + JSON.stringify(value) + "\n\n"; }
function stream(body: string, split = false) {
  const bytes = new TextEncoder().encode(body);
  return new Response(new ReadableStream({ start(controller) {
    if (split) { controller.enqueue(bytes.slice(0, 7)); controller.enqueue(bytes.slice(7, 23)); controller.enqueue(bytes.slice(23)); }
    else controller.enqueue(bytes);
    controller.close();
  } }), { headers: { "Content-Type": "text/event-stream; charset=utf-8" } });
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("parses chunked UTF-8 frames, heartbeats and duplicate replay without duplicating progress", async () => {
  const received: RunEvent[] = [];
  const body = ": heartbeat\r\n\r\n" + frame(event(1)) + frame(event(1)) + frame(event(2, "COMPLETED"));
  expect(await readEvents(stream(body, true), "run", 0, e => received.push(e))).toBe(2);
  expect(received.map(e => e.sequence)).toEqual([1, 2]);
  expect(await readEvents(stream(": heartbeat\n\ndata: unfinished"), "run", 2, vi.fn())).toBe(2);
});

it.each([
  [new Response("unavailable", { status: 503 }), 503],
  [new Response(null, { headers: { "Content-Type": "text/event-stream" } }), 503],
  [new Response("{}", { headers: { "Content-Type": "application/json" } }), 503],
  [new Response("no header"), 503],
  [stream("event: access_lost\ndata: {}\n\n"), 401],
  [stream(frame({ ...event(1), run_id: "other" })), 409],
  [stream(frame({ ...event(1), sequence: 1.5 })), 409],
  [stream(frame(event(0))), 409],
  [stream(frame(event(3))), 409],
  [stream("x".repeat(131073)), 502],
])("rejects unsafe or invalid stream variant %#", async (response, status) => {
  await expect(readEvents(response as Response, "run", 0, vi.fn())).rejects.toMatchObject({ status });
});

it("uses authenticated JSON endpoints for submission, snapshots and cancellation", async () => {
  const fetcher = vi.fn().mockImplementation(async () => Response.json(final));
  vi.stubGlobal("fetch", fetcher);
  expect(await runApi.submit("session", request)).toEqual(final);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(request);
  expect(await runApi.get("session", "run")).toEqual(final);
  expect(await runApi.cancel("session", "run")).toEqual(final);
  expect(fetcher.mock.calls[0][1].headers.get("X-Demo-Session")).toBe("session");
  expect(fetcher.mock.calls[2][0]).toBe("/v1/demo/csv/runs/run/cancel");
});

it("tracks events and confirms a terminal answer using the authoritative snapshot", async () => {
  const fetcher = vi.fn().mockResolvedValue(stream(frame(event(1)) + frame(event(2, "COMPLETED"))));
  vi.stubGlobal("fetch", fetcher);
  const get = vi.spyOn(runApi, "get").mockResolvedValue(final);
  const received: RunSnapshot[] = [];
  const controller = new AbortController();
  expect(await runApi.watch("session", initial, controller.signal, r => received.push(r))).toEqual(final);
  expect(fetcher.mock.calls[0][1].headers["Last-Event-ID"]).toBe("run:0");
  expect(received.map(r => r.sequence)).toEqual([0, 1, 2, 2]);
  expect(get).toHaveBeenCalledOnce();
  expect(terminal("CANCELLED")).toBe(true);
  expect(await runApi.watch("session", final, controller.signal, vi.fn())).toEqual(final);
  expect(fetcher).toHaveBeenCalledOnce();
});

it("recovers an answer when a proxy drops the progress stream", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network interrupted")));
  vi.spyOn(runApi, "get").mockResolvedValue(final);
  expect(await runApi.watch("session", initial, new AbortController().signal, vi.fn())).toEqual(final);
});

it("resumes from the latest snapshot sequence after stream loss", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(stream(frame(event(1))))
    .mockResolvedValueOnce(stream(frame(event(2, "COMPLETED"))));
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(runApi, "get").mockResolvedValueOnce({ ...initial, sequence: 1 }).mockResolvedValueOnce(final);
  expect(await runApi.watch("session", initial, new AbortController().signal, vi.fn())).toEqual(final);
  expect(fetcher.mock.calls[1][1].headers["Last-Event-ID"]).toBe("run:1");
});

it.each([
  { ...final, run_id: "foreign" }, { ...final, sequence: 0 },
  { ...final, source_binding: "foreign" },
  { ...final, request: { ...request, definition_snapshot_id: "foreign" } },
])("rejects snapshot identity, source, definition and sequence changes %#", async snapshot => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream(frame(event(1)))));
  vi.spyOn(runApi, "get").mockResolvedValue(snapshot);
  await expect(runApi.watch("session", initial, new AbortController().signal, vi.fn()))
    .rejects.toMatchObject({ status: 409 });
});

it("bounds reconnects and never resubmits a paid query", async () => {
  const fetcher = vi.fn().mockImplementation(async () => stream(": heartbeat\n\n"));
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(runApi, "get").mockResolvedValue(initial);
  const submit = vi.spyOn(runApi, "submit");
  await expect(runApi.watch("session", initial, new AbortController().signal, vi.fn()))
    .rejects.toMatchObject({ status: 503 });
  expect(fetcher).toHaveBeenCalledTimes(12);
  expect(submit).not.toHaveBeenCalled();
});

it("stops on denied access and on component disconnect", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 401 })));
  const get = vi.spyOn(runApi, "get");
  await expect(runApi.watch("session", initial, new AbortController().signal, vi.fn()))
    .rejects.toMatchObject({ status: 401 });
  expect(get).not.toHaveBeenCalled();
  const controller = new AbortController();
  controller.abort();
  await expect(runApi.watch("session", initial, controller.signal, vi.fn())).rejects.toMatchObject({ name: "AbortError" });
  const runningController = new AbortController();
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => { runningController.abort(); throw new DOMException("Aborted", "AbortError"); }));
  await expect(runApi.watch("session", initial, runningController.signal, vi.fn())).rejects.toMatchObject({ name: "AbortError" });
});

