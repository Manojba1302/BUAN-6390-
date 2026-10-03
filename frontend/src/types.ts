/** Shapes the API returns. Kept in one file so a change is easy to trace. */

export type Widget =
  | "text" | "email" | "number" | "date" | "select" | "currency"
  | "phone" | "ssn" | "zip" | "cards" | "agree";

export interface FieldSpec {
  label: string;
  widget: Widget;
  options?: string;
  required?: boolean;
  help?: string;
  placeholder?: string;
  sensitive?: boolean;
  allow_zero?: boolean;
  step?: string;
  visible_if?: { field: string; equals: string };
}

export interface GroupSpec {
  title: string;
  visible_if?: { field: string; equals: string };
  hint?: string;
  fields?: string[];
  repeatable?: string;
  declarations?: boolean;
  computed?: { id: string; label: string; formula: string }[];
}

export interface StepSpec {
  id: string;
  label: string;
  title: string;
  lede: string;
  groups: GroupSpec[];
}

export interface RepeatableField {
  id: string;
  label: string;
  widget: Widget;
  options?: string;
  required?: boolean;
  placeholder?: string;
}

export interface RepeatableSpec {
  label: string;
  add_label: string;
  add_another_label: string;
  hint?: string;
  fields: RepeatableField[];
}

export type OptionSet = (string | { value: string; label: string; hint?: string })[];

export interface Dictionary {
  version: string;
  option_sets: Record<string, OptionSet>;
  steps: StepSpec[];
  fields: Record<string, FieldSpec>;
  repeatables: Record<string, RepeatableSpec>;
  declarations: { code: string; text: string }[];
}

export interface ChecklistItem {
  document_tag: string;
  display_name: string;
  required_count: number;
  guidance: string | null;
}

export interface FieldValue {
  value: string | null;
  source: "user" | "extracted";
  review_state: "proposed" | "confirmed" | "corrected";
  file_id: string | null;
  page: number | null;
  evidence_quote: string | null;
  method: string | null;
}

export interface ApplicationState {
  application_id: string;
  customer_id?: string;
  status: string;
  current_step: number;
  fields: Record<string, FieldValue>;
  declarations: Record<string, string>;
  employment: Record<string, unknown>[];
  asset: Record<string, unknown>[];
  liability: Record<string, unknown>[];
}

export interface Progress {
  steps: { id: string; label: string; complete: boolean; missing: string[] }[];
  complete: boolean;
  percent: number;
  status: string;
}

export type Outcome = "matched" | "mismatched" | "unknown" | "unreadable" | "failed";

export interface ClassifyResult {
  selected_type: string;
  detected_type: string;
  outcome: Outcome;
  readable: boolean;
  evidence: string[];
  mixed_document: boolean;
  model: string;
  elapsed_ms: number;
  message: string;
}

export interface DocumentSummary {
  file_id: string;
  document_tag: string;
  display_name: string;
  original_name: string;
  content_type: string | null;
  size_bytes: number | null;
  page_count: number | null;
  status: "uploaded" | "queued" | "processing" | "completed" | "failed";
  error: string | null;
  application_id: string | null;
  uploaded_at: string | null;
  classification: {
    selected_type: string; detected_type: string; outcome: Outcome;
    evidence: string[]; mixed_document: boolean; model: string;
  } | null;
  has_markdown: boolean;
}

export interface ExtractionRow {
  extraction_id: string;
  field_name: string;
  value: string | null;
  value_raw: string | null;
  corrected_value: string | null;
  page: number | null;
  evidence_quote: string | null;
  method: string | null;
  review_state: string;
}

export interface DocumentDetail extends DocumentSummary {
  extractions: ExtractionRow[];
  missing_fields: string[];
}

/** A file the customer has chosen but not yet uploaded. */
export interface StagedFile {
  id: string;
  file: File;
  cat: string;
  name: string;
  size: number;
  isPdf: boolean;
  previewUrl: string | null;
  status: "local" | "checking" | "done" | "error";
  result: ClassifyResult | null;
  kept: boolean;
}
