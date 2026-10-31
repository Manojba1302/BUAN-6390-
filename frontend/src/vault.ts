/** Vault folders and vault-only uploads. Kept apart from api.ts so the vault can grow on its own. */
import { ApiError } from "./api";
import type { DocumentSummary, VaultFolder } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api/v1";

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, credentials: "include" });
  } catch {
    throw new ApiError("We could not reach the server. Check your connection.", 0);
  }
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("homeflow:session-expired"));
    const detail = await response.json().catch(() => null);
    const raw = (detail as { detail?: unknown } | null)?.detail;
    throw new ApiError(typeof raw === "string" ? raw : response.status === 413 ? "That file is too large."
      : response.status === 415 ? "Upload a PDF, JPG, PNG or HEIC." : "Something went wrong. Try again.", response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const send = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export interface DocumentVersion {
  file_id: string; version: number; original_name: string; size_bytes: number | null; uploaded_at: string | null; current: boolean;
}

/** One document a loan needs, as the vault's loan card shows it. have counts only documents that were read. */
export interface ChecklistRow {
  document_tag: string; display_name: string; need: number; have: number; reading: number; unread: number;
  files: { file_id: string; original_name: string; status: string }[];
}

export interface VaultUpload {
  file_id: string; status: string; duplicate_of?: string; application_id?: string | null; message?: string;
}

export const vault = {
  folders: () => call<VaultFolder[]>("/documents/folders"),
  createFolder: (name: string) => call<VaultFolder>("/documents/folders", send("POST", { name })),
  deleteFolder: (name: string) => call<void>(`/documents/folders/${encodeURIComponent(name)}`, { method: "DELETE" }),
  moveDocument: (fileId: string, folder: string) =>
    call<DocumentSummary>(`/documents/${fileId}/folder`, send("PATCH", { folder })),
  /** A new version of a document. The earlier one is kept; its applications move to the new one. */
  replace: (fileId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<DocumentSummary>(`/documents/${fileId}/replace`, { method: "POST", body: form });
  },
  versions: (fileId: string) => call<DocumentVersion[]>(`/documents/${fileId}/versions`),
  /** Only a document saved as Other can change type. */
  changeType: (fileId: string, documentTag: string, label: string | null = null) =>
    call<DocumentSummary>(`/documents/${fileId}/type`, send("PATCH", { document_tag: documentTag, label })),
  /** Saved to the vault only and never refused: a file that does not match its type is kept as Other.
   *  Fields are pulled out later, when it is attached to an application. */
  upload: (file: File, documentTag: string, folder: string, label: string | null = null,
           options: { auto?: boolean; applicationId?: string } = {}) => {
    const form = new FormData();
    form.append("file", file);
    form.append("document_tag", documentTag);
    form.append("logical_path", folder ? `/${folder}` : "/");
    if (label) form.append("document_label", label);
    if (options.auto) form.append("auto_type", "true");          // no type chosen: HomeFlow works it out
    if (options.applicationId) form.append("application_id", options.applicationId);
    return call<VaultUpload>("/documents", { method: "POST", body: form });
  },
  /** A draft can be deleted outright; its documents stay in the vault. A sent application cannot. */
  deleteApplication: (applicationId: string) => call<void>(`/applications/${applicationId}`, { method: "DELETE" }),
  /** What one application still needs, document by document. */
  checklist: (applicationId: string) => call<ChecklistRow[]>(`/applications/${applicationId}/checklist`),
  /** Add a document already in the vault to an application. Its details are read from the text kept at upload. */
  attach: (fileId: string, applicationId: string) =>
    call<{ file_id: string; status: string }>(`/documents/${fileId}/link`, send("POST", { application_id: applicationId })),
};

/** How an application is named to the customer: HF- and the first eight characters of its id. */
export const reference = (id: string) => `HF-${id.replaceAll("-", "").slice(0, 8).toUpperCase()}`;

/* ------------------------------------------------ what a document can be */
/** Loan documents: read automatically, and their fields fill in an application. */
export const LOAN_KINDS: { tag: string; name: string; folder: string }[] = [
  { tag: "paystub", name: "Pay stub", folder: "Finances" },
  { tag: "w2", name: "W-2", folder: "Taxes" },
  { tag: "bank_statement", name: "Bank statement", folder: "Finances" },
  { tag: "drivers_license", name: "Driver's license", folder: "Identification & Licenses" },
  { tag: "ssn_card", name: "Social Security card", folder: "Identification & Licenses" },
];

/** Everything else a household keeps (common planning checklist). Stored and searchable; no fields are pulled out. */
export const STORED_KINDS: { folder: string; items: string[] }[] = [
  { folder: "Legal", items: ["Last Will", "Living Will", "Durable Power of Attorney", "Child Support Documents", "Alimony Documents", "Divorce Decree", "Adoption Papers", "Trust Documents"] },
  { folder: "Identification & Licenses", items: ["Birth Certificate", "Passport", "Marriage License", "Immigration Documents", "Military ID", "Death Certificate", "Other Licenses"] },
  { folder: "People & Places", items: ["List of Safety Deposit Boxes", "Key Contacts"] },
  { folder: "Finances", items: ["List of Financial Accounts", "Financial Plans and Budgets", "Account Statements", "Additional Financial Documents", "Credit Report"] },
  { folder: "Taxes", items: ["Annual Income Tax Records", "Property Tax Statements"] },
  { folder: "Insurance & Property", items: ["Life Insurance Policy", "Health Insurance Card", "Home Insurance Policy", "Auto Insurance Policies", "Vehicle Title", "House / Land Deeds"] },
  { folder: "Other", items: ["Transcripts", "Degree(s)", "Licenses to Practice", "Organization Membership Cards"] },
];

export const LOAN_TYPES = LOAN_KINDS.map(k => k.tag);

/** What a loan is for, in the words the customer picked in Get started. */
export function purposeName(purpose?: string | null) {
  if (purpose === "Purchase") return "Home purchase";
  if (purpose === "Other") return "Home equity line";
  return purpose?.includes("Refinance") ? "Refinance" : "Loan application";
}

/** A dropdown value plus the name typed for "Something else", if any. */
export function kindWithName(value: string, typed: string) {
  const name = typed.trim().replace(/\s+/g, " ");
  return value === "other" && name ? { ...kindOf(value), label: name, name } : kindOf(value);
}

/** A dropdown value: a loan tag ("w2"), "label:<name>" for a stored-only kind, or "other" for something else. */
export function kindOf(value: string): { tag: string; label: string | null; name: string; folder: string } {
  const loan = LOAN_KINDS.find(k => k.tag === value);
  if (loan) return { tag: loan.tag, label: null, name: loan.name, folder: loan.folder };
  if (value.startsWith("label:")) {
    const name = value.slice(6);
    return { tag: "other", label: name, name, folder: STORED_KINDS.find(g => g.items.includes(name))?.folder ?? "Other" };
  }
  return { tag: "other", label: null, name: "Other document", folder: "Other" };
}
