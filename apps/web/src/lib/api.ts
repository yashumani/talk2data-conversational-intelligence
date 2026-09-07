import type { ChatResult, DemoSession, Source, WorkspaceState } from "./contracts.ts";

const API = "/v1/demo/csv";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("X-Demo-Session", token);
  const response = await fetch(API + path, {
    ...init, headers, cache: "no-store", signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    let detail = "Request failed. Check the backend and retry.";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (response.status === 422) detail = "The request was invalid. Check the file, question, and date.";
    } catch { /* Reverse proxies may return non-JSON errors. */ }
    if (response.status === 404) detail = "CSV demo is disabled or the backend is unavailable. See the runbook.";
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export const api = {
  createSession: () => request<DemoSession>("/sessions", undefined, { method: "POST" }),
  state: (token: string) => request<WorkspaceState>("/state", token),
  upload: (token: string, file: File) => request<Source>("/upload", token, {
    method: "POST", headers: { "Content-Type": "text/csv" }, body: file,
  }),
  ask: (token: string, question: string, asOf: string, fingerprint: string) =>
    request<ChatResult>("/chat", token, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question, as_of: asOf + "T12:00:00Z", source_fingerprint: fingerprint,
      }),
    }),
  clear: (token: string) => request<void>("/clear", token, { method: "POST" }),
};
