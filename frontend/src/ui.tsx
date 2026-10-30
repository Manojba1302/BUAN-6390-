/** Shared pieces: toasts, the tracker, the rail, the footer, and the field
 *  renderer that draws every input from the dictionary. */
import {
  createContext, useCallback, useContext, useMemo, useState,
  type CSSProperties, type ReactNode,
} from "react";

import { CHOICE_ICON, Icon } from "./icons";
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

export function Rail({ dictionary, progress, step, onGo }: {
  dictionary: Dictionary; progress: Progress | null; step: number;
  applicationId?: string | null;
  onGo: (i: number) => void;
}) {
  return (
    <nav className="rail" aria-label="Application sections">
      <div className="rail-card">
        <p className="rail-title">YOUR APPLICATION</p>
        <p className="rail-progress">Step {step + 1} of {dictionary.steps.length}</p>
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
        {progress && (() => {
          const pct = Math.round(progress.percent);
          const done = progress.steps.filter((s) => s.complete).length;
          return (
            <span className="rail-meter" role="img" aria-label={`Application ${pct}% complete, ${done} of ${dictionary.steps.length} sections done`}
                  style={{ "--v": pct } as CSSProperties}>
              <b>{pct}%</b>
              <span className="rail-meter-bars" aria-hidden="true">
                {dictionary.steps.map((s, i) => (
                  <span key={s.id} style={{ animationDelay: `${i * 0.08}s` }}
                        className={progress.steps[i]?.complete ? "done" : i === step ? "now" : ""} />
                ))}
              </span>
            </span>
          );
        })()}
      </div>
    </nav>
  );
}

/* ------------------------------------------------- application progress */

/** The dark header on every step: step number, title, a short line, and an optional action. */
export function StepHero({ dictionary, step, title, lede, action }: {
  dictionary: Dictionary; step: number; title: ReactNode; lede: ReactNode; action?: ReactNode;
}) {
  return (
    <section className="step-hero" aria-labelledby="step-hero-title">
      <div className="step-hero-top">
        <div className="step-hero-copy">
          <p className="step-hero-eyebrow">Step {step + 1} of {dictionary.steps.length}</p>
          <h1 id="step-hero-title">{title}</h1>
          <p className="step-hero-lede">{lede}</p>
        </div>
        {action}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ footer */
export function FootNav({ step, lastStep, blocking, busy, unsaved, justSaved, saveError, onBack, onNext }: {
  step: number; lastStep: boolean; blocking: string | null; busy: boolean;
  unsaved: boolean; justSaved: boolean; saveError: string;
  onBack: () => void; onNext: () => void;
}) {
  return (
    <div className="footnav">
      <div className="footnav-in">
        {step > 0 && (
          <button className="btn sec" onClick={onBack}><Icon name="back" />Back</button>
        )}
        <div className="footnote"><span className="foot-step">Step {step + 1} of 6</span><span className={blocking ? "foot-status needs-input" : "foot-status"}>{blocking || "Your progress is saved when you continue"}</span></div>
        <div className="save-feedback" aria-live="polite">
          {saveError ? <span className="save-feedback-error" role="alert"><Icon name="alert" />{saveError}</span> : busy ? <span><span className="spin" />Saving…</span> : unsaved ? <span className="save-feedback-unsaved">You have unsaved changes.</span> : justSaved ? <span className="save-feedback-success"><Icon name="check" />Progress saved</span> : null}
        </div>
        <button className="btn" onClick={onNext} disabled={busy}>
          {busy ? "Saving…" : saveError ? "Retry save" : lastStep ? "Submit application" : "Save and continue"}
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
  const [focused, setFocused] = useState(false);
  // Floating label: sits inside the box, moves up when the box has focus or a value.
  const raised = focused || value !== "" || editingSensitive || spec.widget === "select" || spec.widget === "date";
  const focus = () => setFocused(true);

  return (
    <div className={`f fl ${raised ? "up" : ""}`} data-field={name}>
      <label className="cap" htmlFor={id}>
        {spec.label}{spec.required && <span className="req">*</span>}

      </label>

      {spec.sensitive ? (
        <div className="sensitive-control">
          <input id={id} className="ctl" aria-invalid={invalid}
                 type="text" readOnly={!editingSensitive}
                 inputMode="numeric" autoComplete="off" placeholder="Enter your number"
                 value={editingSensitive ? value : maskSensitive(value)}
                 aria-describedby={`${id}_privacy`}
                 onChange={e => onChange(applyMask(spec.widget, e.target.value))}
                 onFocus={focus}
                 onBlur={() => { setFocused(false); setEditingSensitive(false); onBlur(); }}
                 onKeyDown={e => { if (e.key === "Enter") { setEditingSensitive(false); onBlur(); } }} />
          <button type="button" className="sensitive-edit" onMouseDown={e => e.preventDefault()} onClick={() => { setEditingSensitive(v => !v); onBlur(); }}>
            {editingSensitive ? "Done" : value ? "Edit" : "Enter"}
          </button>
          <p id={`${id}_privacy`} className="help">Visible while entering. Only the last four digits appear after Done or leaving this field.</p>
        </div>
      ) : spec.widget === "select" ? (
        <select id={id} className="ctl" value={value} aria-invalid={invalid}
                onChange={(e) => onChange(e.target.value)} onFocus={focus} onBlur={() => { setFocused(false); onBlur(); }}>
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
                 autoComplete="off" onChange={(e) => onChange(e.target.value)} onFocus={focus} onBlur={() => { setFocused(false); onBlur(); }} />
        </div>
      ) : (
        <input id={id} className="ctl" aria-invalid={invalid}
               type={spec.widget === "date" ? "date" : spec.widget === "email" ? "email" : "text"}
               inputMode={["ssn", "zip", "phone", "number"].includes(spec.widget) ? "numeric" : undefined}
               placeholder={spec.placeholder ?? ""}
               value={value}
               onChange={(e) => onChange(applyMask(spec.widget, e.target.value))}
               onFocus={focus} onBlur={() => { setFocused(false); onBlur(); }} />
      )}

      {spec.help && !error && <p className="help">{spec.help}</p>}
      {provenance && (
        <p className="srcline">
          <Icon name="file" />
          <span title={provenance.fileName}>{provenance.fileName}{provenance.page ? ` · Page ${provenance.page}` : ""}</span>
          <button type="button" className="linkish" onClick={() => props.onOpenSource?.(provenance.fileId)}>View source</button>
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
            <span className="ci"><Icon name={CHOICE_ICON[label] ?? "home"} /></span>
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
  const picked = values.indexOf(value ?? "");
  return (
    <span className="seg" style={{ "--seg-n": values.length } as CSSProperties}>
      <span className="seg-thumb" aria-hidden="true"
            style={{ transform: `translateX(${Math.max(0, picked) * 100}%)`, opacity: picked < 0 ? 0 : 1 }} />
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

