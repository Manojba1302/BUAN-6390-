/** Shared pieces: toasts, the tracker, the rail, the footer, and the field
 *  renderer that draws every input from the dictionary. */
import {
  createContext, useCallback, useContext, useMemo, useState,
  type ReactNode,
} from "react";

import { Icon } from "./icons";
import { applyMask, validate, maskSensitive } from "./format";
import type { Dictionary, FieldSpec, OptionSet, Progress } from "./types";

/* ------------------------------------------------------------------ toasts */
type Toast = { id: number; message: string; kind: "ok" | "info" };
const ToastCtx = createContext<(message: string, kind?: "ok" | "info") => void>(() => {});

export const useToast = () => useContext(ToastCtx);

export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((message: string, kind: "ok" | "info" = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, message, kind }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 3200);
  }, []);

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => (
          <div className="toast" key={t.id}>
            <Icon name={t.kind === "ok" ? "check" : "info"} />
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ----------------------------------------------------------------- tracker */
export function Tracker({ dictionary, progress, step, onGo }: {
  dictionary: Dictionary; progress: Progress | null; step: number;
  onGo: (i: number) => void;
}) {
  const steps = dictionary.steps;
  const percent = progress?.percent ?? 0;


  const status = (i: number): string => {
    if (i === step) return "current";
    const s = progress?.steps[i];
    if (i < step) return s && !s.complete ? "attention" : "done";
    return s?.complete ? "done" : "";
  };

  return (
    <div className="tracker">
      <div className="tracker-in">
        <div className="tr-head">
          <b>{steps[step]?.label}</b>
          <span>Step {step + 1} of {steps.length}</span>
        </div>
        <div className="steps">
          {steps.map((s, i) => (
            <button key={s.id} className={`step ${status(i)}`} onClick={() => onGo(i)}
                    disabled={i > step + 1} aria-current={i === step ? "step" : undefined}>
              <span className="bead">{status(i) === "done" ? <Icon name="check" width={3} /> : i + 1}</span>
              <span className="lbl">{s.label}</span>
            </button>
          ))}
        </div>
        <div className="bar"><i style={{ width: `${percent}%` }} /></div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- rail */
const RAIL_ICONS = ["home", "doc", "user", "home", "wallet", "check"];

export function Rail({ dictionary, progress, step, applicationId, onGo }: {
  dictionary: Dictionary; progress: Progress | null; step: number;
  applicationId?: string | null;
  onGo: (i: number) => void;
}) {
  return (
    <nav className="rail" aria-label="Application sections">
      <div className="rail-card">
        <p className="rail-title">YOUR APPLICATION</p>
        <p className="rail-progress">Step {step + 1} of {dictionary.steps.length}</p>
        {applicationId && <div className="rail-reference"><span>Application ID</span><strong title={applicationId}>HF-{applicationId.replaceAll("-", "").slice(0, 8).toUpperCase()}</strong><label>{progress?.steps.filter(s => s.complete).length ?? 0} of {dictionary.steps.length} sections complete</label><label>Application progress · {Math.round(progress?.percent ?? 0)}%</label><progress value={progress?.percent ?? 0} max={100} aria-label="Application progress" /></div>}
        {dictionary.steps.map((s, i) => {
          const state = progress?.steps[i];
          return (
            <a key={s.id} className={i === step ? "on" : ""} role="button" tabIndex={0}
               onClick={() => onGo(i)}
               onKeyDown={(e) => e.key === "Enter" && onGo(i)}>
              <span className="ic"><Icon name={RAIL_ICONS[i] ?? "doc"} /></span>
              <span className="nav-label">{s.label}<small>{state?.complete ? "Complete" : i === step ? "In progress" : state?.missing?.length && i < step ? "Needs attention" : "Not complete"}</small></span>
              {state?.complete && <span className="tick"><Icon name="check" width={3} /></span>}
              {state && !state.complete && i < step && <span className="pill">check</span>}
            </a>
          );
        })}
      </div>
    </nav>
  );
}

/* ------------------------------------------------------------------ footer */
export function FootNav({ step, lastStep, blocking, busy, onBack, onNext }: {
  step: number; lastStep: boolean; blocking: string | null; busy: boolean;
  onBack: () => void; onNext: () => void;
}) {
  return (
    <div className="footnav">
      <div className="footnav-in">
        {step > 0 && (
          <button className="btn sec" onClick={onBack}><Icon name="back" />Back</button>
        )}
        <span className="footnote">{blocking || "Select Save and continue to save your answers."}</span>
        <button className="btn" onClick={onNext} disabled={busy}>
          {busy ? "Saving" : lastStep ? "Submit application" : "Save and continue"}
          {!lastStep && !busy && <Icon name="chevron" />}
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- field */
export interface FieldProps {
  name: string;
  spec: FieldSpec;
  value: string;
  error?: string;
  provenance?: { fileName: string; page: number | null; fileId: string } | null;
  options: OptionSet;
  onChange: (value: string) => void;
  onBlur: () => void;
  onOpenSource?: (fileId: string) => void;
}

export function Field(props: FieldProps) {
  const { name, spec, value, error, provenance, options, onChange, onBlur } = props;
  const id = `f_${name}`;
  const invalid = Boolean(error);
  const [editingSensitive, setEditingSensitive] = useState(false);

  return (
    <div className="f">
      <label className="cap" htmlFor={id}>
        {spec.label}{spec.required && <span className="req">*</span>}
        {provenance && (
          <button type="button" className="aibadge"
                  onClick={() => props.onOpenSource?.(provenance.fileId)}>
            <Icon name="spark" />From your document
          </button>
        )}
      </label>

      {spec.sensitive ? (
        <div className="sensitive-control">
          <input id={id} className="ctl" aria-invalid={invalid}
                 type="text" readOnly={!editingSensitive}
                 inputMode="numeric" autoComplete="off" placeholder="Enter your number"
                 value={editingSensitive ? value : maskSensitive(value)}
                 aria-describedby={`${id}_privacy`}
                 onChange={e => onChange(applyMask(spec.widget, e.target.value))}
                 onBlur={() => { setEditingSensitive(false); onBlur(); }}
                 onKeyDown={e => { if (e.key === "Enter") { setEditingSensitive(false); onBlur(); } }} />
          <button type="button" className="sensitive-edit" onMouseDown={e => e.preventDefault()} onClick={() => { setEditingSensitive(v => !v); onBlur(); }}>
            {editingSensitive ? "Done" : value ? "Edit" : "Enter"}
          </button>
          <p id={`${id}_privacy`} className="help">Visible while entering. Only the last four digits appear after Done or leaving this field.</p>
        </div>
      ) : spec.widget === "select" ? (
        <select id={id} className="ctl" value={value} aria-invalid={invalid}
                onChange={(e) => onChange(e.target.value)} onBlur={onBlur}>
          <option value="">Select one</option>
          {options.map((o) => {
            const v = typeof o === "string" ? o : o.value;
            const l = typeof o === "string" ? o : o.label;
            return <option key={v} value={v}>{l}</option>;
          })}
        </select>
      ) : spec.widget === "currency" ? (
        <div className="money">
          <span className="sym">$</span>
          <input id={id} className="ctl" inputMode="decimal" value={value} aria-invalid={invalid}
                 autoComplete="off" onChange={(e) => onChange(e.target.value)} onBlur={onBlur} />
        </div>
      ) : (
        <input id={id} className="ctl" aria-invalid={invalid}
               type={spec.widget === "date" ? "date" : spec.widget === "email" ? "email" : "text"}
               inputMode={["ssn", "zip", "phone", "number"].includes(spec.widget) ? "numeric" : undefined}
               placeholder={spec.placeholder ?? ""}
               value={value}
               onChange={(e) => onChange(applyMask(spec.widget, e.target.value))}
               onBlur={onBlur} />
      )}

      {spec.help && !error && <p className="help">{spec.help}</p>}
      {provenance && (
        <p className="srcline">
          <Icon name="file" />
          <span>Read from <b>{provenance.fileName}</b>{provenance.page ? `, page ${provenance.page}` : ""}.</span>
          <button className="linkish" onClick={() => props.onOpenSource?.(provenance.fileId)}>See it</button>
        </p>
      )}
      {error && <p className="err"><Icon name="alert" /><span>{error}</span></p>}
    </div>
  );
}

/* ------------------------------------------------------------ choice cards */
export function Cards({ options, value, onChange }: {
  options: OptionSet; value: string; onChange: (v: string) => void;
}) {
  return (
    <div className="choices c2">
      {options.map((o) => {
        const v = typeof o === "string" ? o : o.value;
        const label = typeof o === "string" ? o : o.label;
        const hint = typeof o === "string" ? "" : o.hint ?? "";
        return (
          <button key={v} type="button" aria-pressed={value === v} className={`choice ${value === v ? "on" : ""}`} onClick={() => onChange(v)}>
            <span className="ci"><Icon name={{ Employed: "wallet", "Self-employed": "folder", Retired: "user", "Not currently employed": "refresh", Other: "chat" }[v] ?? "home"} /></span>
            <span className="choice-copy"><b>{label}</b><span>{hint}</span></span>
            <span className="choice-radio" aria-hidden="true">{value === v && <Icon name="check" />}</span>
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------- yes/no pair */
export function Segmented({ value, onChange, labels = ["Yes", "No"], values = ["yes", "no"] }: {
  value: string | undefined; onChange: (v: string) => void;
  labels?: [string, string] | string[]; values?: [string, string] | string[];
}) {
  return (
    <span className="seg">
      {values.map((v, i) => (
        <button key={v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>
          {labels[i]}
        </button>
      ))}
    </span>
  );
}

/** Resolve an option set name to its list, with a safe fallback. */
export function useOptions(dictionary: Dictionary, name?: string): OptionSet {
  return useMemo(() => (name ? dictionary.option_sets[name] ?? [] : []), [dictionary, name]);
}

export { validate };

