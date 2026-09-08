import { ApiError, request } from "./api";
import type { AgentRun, ChatResult } from "./contracts";

export interface RunRequest {
  client_request_id: string;
  conversation_id: string;
  expected_revision: number;
  question: string;
  as_of: string;
  source_fingerprint: string;
  definition_snapshot_id: string;
}
export interface RunSnapshot {
  run_id: string;
  request: RunRequest;
  source_binding: string;
  status: string;
  sequence: number;
  progress: AgentRun | null;
  result: ChatResult | null;
  error_code: string | null;
  message: string;
}
export interface RunEvent {
  run_id: string;
  sequence: number;
  status: string;
  progress: AgentRun | null;
}
export interface SyncState {
  enabled: boolean;
  durable: boolean;
  conversation: { conversation_id: string; revision: number; latest_run_id: string | null; title: string };
  runs: { run_id: string; status: string; question: string }[];
}

export function terminal(status: string) {
  return ["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(status);
}

export async function readEvents(response: Response, runId: string, after: number,
  receive: (event: RunEvent) => void): Promise<number> {
  if (!response.ok) throw new ApiError(response.status, "Progress is unavailable. Resume to reconnect.");
  if (!response.body || !response.headers.get("content-type")?.startsWith("text/event-stream"))
    throw new ApiError(503, "The backend did not return a progress stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer = (buffer + decoder.decode(chunk.value, { stream: true })).replaceAll("\r\n", "\n");
      if (buffer.length > 131072) throw new ApiError(502, "The progress stream exceeded its size limit.");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (frame.includes("event: access_lost")) throw new ApiError(401, "Access to this run has expired or changed.");
        const data = frame.split("\n").filter(line => line.startsWith("data: ")).map(line => line.slice(6)).join("\n");
        if (!data) continue;
        const event: RunEvent = JSON.parse(data);
        if (event.run_id !== runId || !Number.isInteger(event.sequence) || event.sequence < 1)
          throw new ApiError(409, "Progress did not match the selected run.");
        if (event.sequence <= after) continue;
        if (event.sequence !== after + 1) throw new ApiError(409, "Progress history has a gap. Refresh the run.");
        receive(event);
        after = event.sequence;
      }
    }
    return after;
  } finally { await reader.cancel(); reader.releaseLock(); }
}

export const runApi = {
  submit: (token: string, payload: RunRequest) => request<RunSnapshot>("/runs", token, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }),
  get: (token: string, runId: string) => request<RunSnapshot>(`/runs/${encodeURIComponent(runId)}`, token),
  cancel: (token: string, runId: string) => request<RunSnapshot>(`/runs/${encodeURIComponent(runId)}/cancel`, token, { method: "POST" }),
  async watch(token: string, initial: RunSnapshot, signal: AbortSignal,
    receive: (run: RunSnapshot) => void): Promise<RunSnapshot> {
    let current = initial;
    receive(current);
    for (let connection = 0; connection < 12 && !terminal(current.status); connection++) {
      signal.throwIfAborted();
      try {
        const response = await fetch(`/v1/demo/csv/runs/${encodeURIComponent(current.run_id)}/events`, {
          headers: { "X-Demo-Session": token, "Last-Event-ID": `${current.run_id}:${current.sequence}` },
          cache: "no-store", redirect: "error", signal: AbortSignal.any([signal, AbortSignal.timeout(25_000)]),
        });
        await readEvents(response, current.run_id, current.sequence, event => {
          current = { ...current, status: event.status, sequence: event.sequence, progress: event.progress };
          receive(current);
        });
      } catch (failure) {
        if (signal.aborted || (failure instanceof ApiError && failure.status < 500)) throw failure;
        // A snapshot can recover a result even when a proxy interrupted its event stream.
      }
      const next = await runApi.get(token, current.run_id);
      if (next.run_id !== current.run_id || next.sequence < current.sequence
        || next.source_binding !== initial.source_binding
        || next.request.definition_snapshot_id !== initial.request.definition_snapshot_id)
        throw new ApiError(409, "The run snapshot changed identity, source, definition or event order.");
      current = next;
      receive(current);
    }
    if (!terminal(current.status)) throw new ApiError(503, "Progress disconnected. Resume the existing run to continue.");
    return current;
  },
};
