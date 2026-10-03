/** Masks, formatting and validation. Pure functions, easy to test. */
import type { FieldSpec } from "./types";

export const num = (v: unknown): number => {
  const n = parseFloat(String(v ?? "").replace(/[^0-9.-]/g, ""));
  return Number.isNaN(n) ? 0 : n;
};

export const money = (v: unknown): string =>
  "$" + num(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

export const money2 = (v: unknown): string =>
  "$" + num(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const bytes = (b: number | null): string =>
  b == null ? "" : b < 1024 * 1024 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1024 / 1024).toFixed(1)} MB`;

export function applyMask(widget: string, value: string): string {
  if (widget === "ssn") {
    const d = value.replace(/\D/g, "").slice(0, 9);
    if (d.length > 5) return `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}`;
    if (d.length > 3) return `${d.slice(0, 3)}-${d.slice(3)}`;
    return d;
  }
  if (widget === "phone") {
    const d = value.replace(/\D/g, "").slice(0, 10);
    if (d.length > 6) return `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`;
    if (d.length > 3) return `(${d.slice(0, 3)}) ${d.slice(3)}`;
    return d;
  }
  if (widget === "zip") return value.replace(/\D/g, "").slice(0, 5);
  return value;
}

export function validate(spec: FieldSpec, raw: string | null | undefined): string {
  const value = (raw ?? "").trim();
  if (spec.required && !value) return `${spec.label} is required`;
  if (!value) return "";
  if (spec.widget === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) {
    return "Enter a valid email address";
  }
  if (spec.widget === "ssn" && value.replace(/\D/g, "").length !== 9) {
    return "A Social Security number has 9 digits";
  }
  if (spec.widget === "zip" && value.length !== 5) return "A ZIP code has 5 digits";
  if (spec.widget === "phone" && value.replace(/\D/g, "").length !== 10) {
    return "A phone number has 10 digits";
  }
  if (spec.widget === "currency") {
    const amount = Number(value.replace(/[$,]/g, ""));
    if (!Number.isFinite(amount) || amount < 0 || (!spec.allow_zero && amount === 0)) return spec.allow_zero ? "Enter zero or a positive amount" : "Enter an amount greater than zero";
  }
  return "";
}

/** Masked until the customer asks to see it. */
export function maskSensitive(value: string): string {
  if (!value) return "";
  if (value.length <= 4) return "•".repeat(value.length);
  return "•".repeat(value.length - 4) + value.slice(-4);
}

export const fieldLabelFromName = (name: string): string =>
  name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
