/** Every call to the back end goes through here. */
import type {
  ApplicationState, ChecklistItem, ClassifyResult, Dictionary,
  DocumentDetail, DocumentSummary, Progress,
} from "./types";

export interface ChatReply {
  answer: string; document_links?: {file_id: string; original_name: string}[];
  citations: {file_id: string; page: number}[];
  evidence: {file_id: string; original_name: string; page: number}[];
}
export interface SavedChatTurn {
  turn_id: string; question: string; reply: ChatReply | null; error: string | null;
  status: "pending" | "completed" | "failed"; source_status: Record<string, string>; created_at: string;
}

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
    if (init.signal?.aborted) throw new ApiError("The assistant took too long. Please try again.", 408);
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

/** Sends a chat message and reads the Server-Sent Events reply: draft text while the model
 *  writes ("token"), then the verified, saved turn ("done"). */
async function streamChat(id: string, question: string, onDraft: (text: string) => void, signal?: AbortSignal, contextAfter?: string): Promise<SavedChatTurn> {
  const response = await fetch(`${BASE}/chat/conversations/${id}/messages/stream`, {...json({question, context_after: contextAfter}), method: "POST", credentials: "include",
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(150000)]) : AbortSignal.timeout(150000)}).catch(() => {
    throw new ApiError(signal?.aborted ? "Request stopped. You can ask again." : "We could not reach the server. Check your connection.", 0);
  });
  if (!response.ok || !response.body) {
    if (response.status === 401) window.dispatchEvent(new Event("homeflow:session-expired"));
    throw new ApiError(messageFor(response.status, await response.json().catch(() => null)), response.status);
  }
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let split: number;
    while ((split = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, split); buffer = buffer.slice(split + 2);
      const kind = /^event: (.*)$/m.exec(block)?.[1]; const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? "null");
      if (kind === "token") onDraft(data.text);
      else if (kind === "done") return data as SavedChatTurn;
      else if (kind === "error") throw new ApiError(data?.detail ?? "We could not answer that. Please try again.", 500);
    }
    if (done) throw new ApiError("The answer was interrupted. Please ask again.", 0);
  }
}

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
    return request<{ file_id: string; status: string; message?: string; duplicate_of?: string; application_id?: string | null }>(
      "/documents", { method: "POST", headers: headers(), body: form });
  },

  documents: (applicationId?: string) =>
    request<DocumentSummary[]>(
      `/documents${applicationId ? `?application_id=${applicationId}` : ""}`,
      { headers: headers() }),

  retryDocument: (fileId: string) => request<void>(`/documents/${fileId}/retry`, {method:"POST"}),

  document: (fileId: string) =>
    request<DocumentDetail>(`/documents/${fileId}`, { headers: headers() }),

  documentStatus: (fileId: string) =>
    request<{ status: string; error: string | null }>(
      `/documents/${fileId}/status`, { headers: headers() }),

  contentUrl: (fileId: string) => `${BASE}/documents/${fileId}/content`,

  correct: (fileId: string, corrections: { extraction_id?: string; field_name?: string; value: string }[]) =>
    request<{ corrected: number }>(`/documents/${fileId}/extractions`, json({ corrections })),

  linkDocument: (fileId: string, applicationId: string) =>
    request(`/documents/${fileId}/link`, { ...json({ application_id: applicationId }), method: "POST" }),

  deleteDocument: (fileId: string) =>
    request<void>(`/documents/${fileId}/permanent`, { method: "DELETE", headers: headers() }),

  unlink: (fileId: string) =>
    request<void>(`/documents/${fileId}`, { method: "DELETE", headers: headers() }),

  documentTemplates: () => request<{template_id:string;name:string;version:string}[]>("/template-documents"),
  renderTemplate: (applicationId:string,templateId:string) => request<{markdown:string;missing_fields:string[];version:string;pdf_base64:string;pages:string[]}>("/template-documents/render",{...json({application_id:applicationId,template_id:templateId}),method:"POST"}),
  conversations: (applicationId: string) => request<{conversation_id: string; created_at: string; updated_at: string; title: string; question_count: number}[]>(`/chat/conversations?application_id=${applicationId}`),
  newConversation: (applicationId: string) => request<{conversation_id: string}>("/chat/conversations", {...json({application_id:applicationId}), method:"POST"}),
  chatHistory: (id: string) => request<{conversation_id: string; turns: SavedChatTurn[]}>(`/chat/conversations/${id}`),
  resumeChatSession: (id: string, contextAfter: string) => request<void>(`/chat/conversations/${id}/resume`, {...json({context_after:contextAfter}),method:"POST"}),
  endChatSession: (id: string, contextAfter: string) => request<void>(`/chat/conversations/${id}/end`, {...json({context_after:contextAfter}),method:"POST"}),
  deleteConversation: (id: string) => request<void>(`/chat/conversations/${id}`, {method:"DELETE"}),
  streamMessage: streamChat,
  sendMessage: (id: string, question: string, signal?: AbortSignal, contextAfter?: string) => request<SavedChatTurn>(`/chat/conversations/${id}/messages`, {...json({question, context_after:contextAfter}), method:"POST", signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(150000)]) : AbortSignal.timeout(150000)}),

  ask: (question: string, applicationId: string, signal?: AbortSignal) =>
    request<{ answer: string; document_links?: { file_id: string; original_name: string }[]; citations: { file_id: string; page: number }[]; evidence: { file_id: string; original_name: string; page: number }[] }>(
      "/chat", {
        method: "POST",
        headers: headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({ question, application_id: applicationId }),
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(150000)]) : AbortSignal.timeout(150000),
      }),
};



