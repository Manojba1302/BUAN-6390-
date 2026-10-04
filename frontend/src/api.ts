/** Every call to the back end goes through here. */
import type {
  ApplicationState, ChecklistItem, ClassifyResult, Dictionary,
  DocumentDetail, DocumentSummary, Progress,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api/v1";

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return { ...extra };
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, credentials: "include" });
  } catch {
    throw new ApiError("We could not reach the server. Check your connection.", 0);
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new Event("homeflow:session-expired"));
    const detail = await response.json().catch(() => null);
    throw new ApiError(messageFor(response.status, detail), response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function messageFor(status: number, detail: unknown): string {
  const raw = (detail as { detail?: unknown })?.detail;
  if (typeof raw === "string") return raw;
  if (raw && typeof raw === "object" && "message" in raw) {
    return String((raw as { message: unknown }).message);
  }
  if (status === 413) return "That file is too large.";
  if (status === 415) return "Upload a PDF, JPG, PNG or HEIC.";
  if (status === 401) return "Your session has expired. Sign in again.";
  return "Something went wrong. Try again.";
}

const json = (body: unknown): RequestInit => ({
  method: "PATCH",
  headers: headers({ "Content-Type": "application/json" }),
  body: JSON.stringify(body),
});

export interface CustomerProfile { customer_id: string; email: string; first_name: string; last_name: string }
export const auth = {
  me: () => request<CustomerProfile>("/auth/me"),
  submit: (route: string, body: Record<string,string>) => request<CustomerProfile & {message?:string}>(`/auth/${route}`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}),
  logout: () => request("/auth/logout", {method:"POST"}),
};
export const api = {
  dictionary: () => request<Dictionary>("/field-definitions"),
  checklist: () => request<ChecklistItem[]>("/checklist"),

  createApplication: () =>
    request<{ application_id: string }>("/applications", { method: "POST", headers: headers() }),

  listApplications: () =>
    request<{ application_id: string; status: string }[]>("/applications", { headers: headers() }),

  getApplication: (id: string) =>
    request<ApplicationState>(`/applications/${id}`, { headers: headers() }),

  patchApplication: (id: string, body: Record<string, unknown>) =>
    request<ApplicationState>(`/applications/${id}`, json(body)),

  progress: (id: string) =>
    request<Progress>(`/applications/${id}/progress`, { headers: headers() }),

  submit: (id: string) =>
    request<{ status: string; reference: string }>(
      `/applications/${id}/submit`, { method: "POST", headers: headers() }),

  /** Stage 1. The file is sent for a look and nothing is stored. */
  classify: (file: File, documentTag: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("document_tag", documentTag);
    return request<ClassifyResult>("/documents/classify",
      { method: "POST", headers: headers(), body: form });
  },

  upload: (file: File, documentTag: string, applicationId: string, confirmedMismatch: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("document_tag", documentTag);
    form.append("application_id", applicationId);
    form.append("confirmed_mismatch", String(confirmedMismatch));
    return request<{ file_id: string; status: string; message?: string }>(
      "/documents", { method: "POST", headers: headers(), body: form });
  },

  documents: (applicationId?: string) =>
    request<DocumentSummary[]>(
      `/documents${applicationId ? `?application_id=${applicationId}` : ""}`,
      { headers: headers() }),

  document: (fileId: string) =>
    request<DocumentDetail>(`/documents/${fileId}`, { headers: headers() }),

  documentStatus: (fileId: string) =>
    request<{ status: string; error: string | null }>(
      `/documents/${fileId}/status`, { headers: headers() }),

  contentUrl: (fileId: string) => `${BASE}/documents/${fileId}/content`,

  correct: (fileId: string, corrections: { extraction_id: string; value: string }[]) =>
    request<{ corrected: number }>(`/documents/${fileId}/extractions`, json({ corrections })),

  linkDocument: (fileId: string, applicationId: string) =>
    request(`/documents/${fileId}/link`, { ...json({ application_id: applicationId }), method: "POST" }),

  deleteDocument: (fileId: string) =>
    request<void>(`/documents/${fileId}/permanent`, { method: "DELETE", headers: headers() }),

  unlink: (fileId: string) =>
    request<void>(`/documents/${fileId}`, { method: "DELETE", headers: headers() }),

  ask: (question: string, applicationId: string) =>
    request<{ answer: string; evidence: { original_name: string; page: number }[] }>(
      "/chat", {
        method: "POST",
        headers: headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({ question, application_id: applicationId }),
      }),
};



