import { ApiError } from "../lib/api";
import type { DefinitionView } from "../lib/definitions";
import { readEvents, terminal, type RunRequest, type RunSnapshot } from "../lib/runs";

export type InternalRequest = Omit<RunRequest, "source_fingerprint">;
export type InternalRun = Omit<RunSnapshot, "request"> & { request: InternalRequest };
export interface Conversation { conversation_id: string; revision: number; title: string; latest_run_id: string | null }
export interface History { conversation: Conversation; runs: { run_id: string; status: string; question: string }[] }
export interface Identity { user_id: string; tenant_id: string; scope_id: string; source_binding: string }
const prefix = "/v1/internal";

export async function internalRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(prefix + path, {
    ...init, credentials: "same-origin", cache: "no-store", redirect: "error",
    signal: AbortSignal.timeout(30_000),
    headers: { "Content-Type": "application/json", "X-T2D-Request": "1" },
  });
  if (!response.ok) throw new ApiError(response.status,
    response.status === 401 || response.status === 403 ? "Your signed session expired or access changed. Sign in again."
      : "The request could not complete. Refresh to recover the existing question.");
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export const internalApi = {
  async load() {
    const [identity, definitions, conversations, language] = await Promise.all([
      internalRequest<Identity>("/me"), internalRequest<DefinitionView>("/definitions"),
      internalRequest<Conversation[]>("/conversations"), internalRequest<{ provider: string }>("/language"),
    ]);
    return { identity, definitions, conversations, language };
  },
  create: () => internalRequest<Conversation>("/conversations", { method: "POST" }),
  history: (id: string) => internalRequest<History>(`/conversations/${encodeURIComponent(id)}`),
  remove: (id: string) => internalRequest<void>(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }),
  submit: (payload: InternalRequest) => internalRequest<InternalRun>("/runs", { method: "POST", body: JSON.stringify(payload) }),
  get: (id: string) => internalRequest<InternalRun>(`/runs/${encodeURIComponent(id)}`),
  cancel: (id: string) => internalRequest<InternalRun>(`/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  async watch(initial: InternalRun, signal: AbortSignal, receive: (run: InternalRun) => void) {
    let current = initial;
    receive(current);
    for (let attempt = 0; attempt < 12 && !terminal(current.status); attempt++) {
      signal.throwIfAborted();
      try {
        const response = await fetch(`${prefix}/runs/${encodeURIComponent(current.run_id)}/events`, {
          credentials: "same-origin", cache: "no-store", redirect: "error",
          headers: { "Last-Event-ID": `${current.run_id}:${current.sequence}` },
          signal: AbortSignal.any([signal, AbortSignal.timeout(25_000)]),
        });
        await readEvents(response, current.run_id, current.sequence, event => {
          current = { ...current, ...event }; receive(current);
        });
      } catch (failure) {
        if (signal.aborted || (failure instanceof ApiError && failure.status < 500)) throw failure;
      }
      const next = await internalApi.get(current.run_id);
      if (next.run_id !== initial.run_id || next.sequence < current.sequence
        || next.source_binding !== initial.source_binding
        || next.request.definition_snapshot_id !== initial.request.definition_snapshot_id
        || next.request.conversation_id !== initial.request.conversation_id)
        throw new ApiError(409, "The saved run identity, source or definition changed.");
      current = next; receive(current);
    }
    if (!terminal(current.status)) throw new ApiError(503, "Progress disconnected. Resume the existing question.");
    return current;
  },
};
