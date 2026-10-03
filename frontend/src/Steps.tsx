/** Every step except documents is rendered straight from the field dictionary.
 *  Adding a field to the JSON adds it to the screen, with no change here. */
import { Icon } from "./icons";
import { money, money2, num } from "./format";
import { Cards, Field, Segmented } from "./ui";
import type {
  Dictionary, FieldSpec, GroupSpec, Progress, RepeatableSpec, StepSpec,
} from "./types";

export interface Provenance { fileName: string; page: number | null; fileId: string }

export interface StepProps {
  dictionary: Dictionary;
  step: StepSpec;
  values: Record<string, string>;
  errors: Record<string, string>;
  provenance: Record<string, Provenance>;
  declarations: Record<string, string>;
  rows: Record<string, Record<string, unknown>[]>;
  onChange: (name: string, value: string) => void;
  onBlur: (name: string) => void;
  onDeclaration: (code: string, answer: string) => void;
  onRows: (kind: string, rows: Record<string, unknown>[]) => void;
  onOpenSource: (fileId: string) => void;
  progress: Progress | null;
  onGo: (i: number) => void;
}

export function FormStep(props: StepProps) {
  const { dictionary, step } = props;
  const focused = dictionary.steps[0]?.id === step.id;
  return (
    <>
      <p className="eyebrow">Step {dictionary.steps.findIndex((s) => s.id === step.id) + 1}</p>
      <h1 className="h1">{step.title}</h1>
      <p className="lede">{step.lede}</p>
      {focused && <>
        <div className="journey-start"><div><b>{props.values.firstName ? `Welcome, ${props.values.firstName}.` : "Choose your starting point"}</b><p>Answer a few questions, or upload your documents first and review any suggested answers.</p></div><button className="btn sec" onClick={() => props.onGo(1)}><Icon name="upload" />Start with documents</button></div>
      </>}
      {step.groups.map((group, i) => (
        <Group key={`${step.id}-${i}`} group={group} {...props} />
      ))}
      {step.id === "review" && <Summary {...props} />}
    </>
  );
}

function visible(spec: FieldSpec, values: Record<string, string>): boolean {
  if (!spec.visible_if) return true;
  return values[spec.visible_if.field] === spec.visible_if.equals;
}

function Group(props: StepProps & { group: GroupSpec }) {
  const { group, dictionary, values, errors, provenance, onChange, onBlur, onOpenSource } = props;

  if (group.visible_if && values[group.visible_if.field] !== group.visible_if.equals) return null;
  if (group.declarations) return <Declarations {...props} />;
  if (group.repeatable) return <Repeatable {...props} kind={group.repeatable} title={group.title} />;

  const names = (group.fields ?? []).filter((n) => {
    const spec = dictionary.fields[n];
    return spec && visible(spec, values);
  });

  const cardFields = names.filter((n) => dictionary.fields[n].widget === "cards");
  const agreeFields = names.filter((n) => dictionary.fields[n].widget === "agree");
  const plain = names.filter((n) => !["cards", "agree"].includes(dictionary.fields[n].widget));

  return (
    <section className="card">
      <h2>{group.title}</h2>
      {group.hint && <p className="hint">{group.hint}</p>}

      {cardFields.map((name) => (
        <Cards key={name} options={dictionary.option_sets[dictionary.fields[name].options ?? ""] ?? []}
               value={values[name] ?? ""} onChange={(v) => onChange(name, v)} />
      ))}

      {plain.length > 0 && (
        <div className="grid g2">
          {plain.map((name) => (
            <Field key={name} name={name} spec={dictionary.fields[name]}
                   value={values[name] ?? ""} error={errors[name]}
                   provenance={provenance[name] ?? null}
                   options={dictionary.option_sets[dictionary.fields[name].options ?? ""] ?? []}
                   onChange={(v) => onChange(name, v)} onBlur={() => onBlur(name)}
                   onOpenSource={onOpenSource} />
          ))}
        </div>
      )}

      {agreeFields.map((name) => <EConsent key={name} {...props} name={name} />)}

      {(group.computed ?? []).map((c) => (
        <div className="totrow" key={c.id}>
          <b>{c.label}</b>
          <span className="amt">{computed(c.formula, values)}</span>
        </div>
      ))}
    </section>
  );
}

function computed(formula: string, values: Record<string, string>): string {
  if (formula.startsWith("sum(")) {
    const prefix = formula.slice(4, -1).replace("*", "");
    const total = Object.entries(values)
      .filter(([k]) => k.startsWith(prefix))
      .reduce((a, [, v]) => a + num(v), 0);
    return money2(total);
  }
  const [left, right] = formula.split("-").map((s) => s.trim());
  return money(Math.max(0, num(values[left]) - num(values[right])));
}

/* ----------------------------------------------------------- repeatables */
function Repeatable(props: StepProps & { kind: string; title: string }) {
  const { dictionary, kind, rows, onRows, title } = props;
  const spec: RepeatableSpec | undefined = dictionary.repeatables[kind];
  if (!spec) return null;
  const list = rows[kind] ?? [];

  const update = (index: number, key: string, value: string) => {
    const next = list.map((row, i) => (i === index ? { ...row, [key]: value } : row));
    onRows(kind, next);
  };

  const total = list.reduce((a, row) =>
    a + num(row.base) + num(row.overtime) + num(row.bonuses) + num(row.commissions), 0);

  return (
    <section className="card">
      <h2>{title}</h2>
      {spec.hint && <p className="hint">{spec.hint}</p>}

      {list.map((row, index) => (
        <div className="rep" key={index}>
          <div className="rep-head">
            <b>{String(row[spec.fields[0].id] ?? "") || `${spec.label} ${index + 1}`}</b>
            {row.source_file_id ? <span className="chip a"><Icon name="spark" />From your document</span> : null}
            <button className="xbtn" aria-label="Remove"
                    onClick={() => onRows(kind, list.filter((_, i) => i !== index))}>
              <Icon name="trash" />
            </button>
          </div>
          <div className="grid g2">
            {spec.fields.map((f) => (
              <div className="f" key={f.id}>
                <label className="cap" htmlFor={`${kind}${index}_${f.id}`}>{f.label}</label>
                {f.widget === "select" ? (
                  <select id={`${kind}${index}_${f.id}`} className="ctl"
                          value={String(row[f.id] ?? "")}
                          onChange={(e) => update(index, f.id, e.target.value)}>
                    <option value="">Select one</option>
                    {(dictionary.option_sets[f.options ?? ""] ?? []).map((o) => {
                      const v = typeof o === "string" ? o : o.value;
                      return <option key={v} value={v}>{typeof o === "string" ? o : o.label}</option>;
                    })}
                  </select>
                ) : f.widget === "currency" ? (
                  <div className="money">
                    <span className="sym">$</span>
                    <input id={`${kind}${index}_${f.id}`} className="ctl" inputMode="decimal"
                           value={String(row[f.id] ?? "")}
                           onChange={(e) => update(index, f.id, e.target.value)} />
                  </div>
                ) : (
                  <input id={`${kind}${index}_${f.id}`} className="ctl"
                         type={f.widget === "date" ? "date" : "text"}
                         placeholder={f.placeholder ?? ""}
                         value={String(row[f.id] ?? "")}
                         onChange={(e) => update(index, f.id, e.target.value)} />
                )}
                {f.id === "base" && row.pay_frequency ? (
                  <p className="help">
                    {String(row.pay_frequency)} pay converted to a monthly figure. Change it if that is wrong.
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ))}

      <button className="addbtn" onClick={() => onRows(kind, [...list, {}])}>
        <Icon name="plus" />{list.length ? spec.add_another_label : spec.add_label}
      </button>

      {kind === "employment" && list.length > 0 && (
        <div className="totrow">
          <b>Total monthly income</b><span className="amt">{money2(total)}</span>
        </div>
      )}
    </section>
  );
}

/* ---------------------------------------------------------- declarations */
function Declarations(props: StepProps) {
  const { dictionary, declarations, onDeclaration } = props;
  const unanswered = dictionary.declarations.filter((d) => !declarations[d.code]).length;

  return (
    <section className="card">
      <h2>Declarations</h2>
      <p className="hint">
        Fourteen questions every lender has to ask. Answer them yourself: we never fill these
        in for you, and nothing in your documents can answer them.
      </p>
      <div style={{ marginTop: 8 }}>
        {dictionary.declarations.map((d) => (
          <div className="decl" key={d.code}>
            <span className="q"><em>{d.code}.</em>{d.text}</span>
            <Segmented value={declarations[d.code]} onChange={(v) => onDeclaration(d.code, v)} />
          </div>
        ))}
      </div>
      {unanswered > 0 && (
        <p className="err"><Icon name="alert" />
          <span>{unanswered} declaration{unanswered > 1 ? "s" : ""} still need an answer</span>
        </p>
      )}
    </section>
  );
}

/* -------------------------------------------------------------- eConsent */
function EConsent(props: StepProps & { name: string }) {
  const { name, values, onChange } = props;
  return (
    <>
      <p className="hint">Three things this means, in plain words.</p>
      <ul style={{ fontSize: 14, paddingLeft: 20, marginTop: 10 }}>
        <li>We send your disclosures by email instead of post.</li>
        <li>You can sign them on screen, and that signature is legally binding.</li>
        <li>You can ask for paper at any time, free, and change your mind later.</li>
      </ul>
      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: "pointer", fontSize: 14, fontWeight: 600, color: "var(--accent)" }}>
          Read the full agreement
        </summary>
        <div className="legal">
          <p>You have indicated that you wish to receive and sign the documents relating to your
            mortgage loan application, closing disclosures and other mortgage-related
            communications electronically.</p>
          <p>You are not required to receive or sign documents electronically, and you acknowledge
            that electronic signatures are equivalent and equally binding as traditional
            signatures. If you do not consent, contact us to arrange paper documents.</p>
          <p>You may withdraw your consent at any time. Withdrawing consent may delay your
            transaction. All actions taken before withdrawing consent remain valid.</p>
        </div>
      </details>
      <div style={{ marginTop: 16 }}>
        <Segmented value={values[name]} labels={["I agree", "I do not agree"]}
                   values={["agree", "decline"]} onChange={(v) => onChange(name, v)} />
      </div>
      {values[name] === "decline" && (
        <div className="banner w" style={{ marginTop: 14 }}>
          <Icon name="alert" />
          <div>
            <b>We cannot continue online without this</b>
            Contact your loan officer to discuss receiving paper documents.
          </div>
        </div>
      )}
    </>
  );
}

/* --------------------------------------------------------------- summary */
function Summary(props: StepProps) {
  const { progress, onGo, dictionary, values } = props;
  if (!progress) return null;
  return (
    <section style={{ marginTop: 20 }}>
      <h2 style={{ fontSize: 19, fontWeight: 600 }}>Your application</h2>
      {progress.steps.map((s, i) => (
        <div className="sumsec" key={s.id}>
          <div className="sumsec-h" style={{ cursor: "default" }}>
            <b>{s.label}</b>
            {s.complete
              ? <span className="chip g"><Icon name="check" />Complete</span>
              : <span className="chip w">{s.missing.length} missing</span>}
            {!s.complete && (
              <button className="linkish" onClick={() => onGo(i)}>Fix it</button>
            )}
          </div>
          <div className="sumsec-b">
              {Object.entries(dictionary.fields).filter(([name, spec]) => spec.step === s.id && visible(spec, values) && values[name] && !spec.sensitive).map(([name, spec]) => <div className="kv" key={name}><span className="k">{spec.label}</span><span className="v">{spec.widget === "currency" ? money2(num(values[name])) : values[name]}</span></div>)}
              {s.missing.map((m) => (
                <div className="kv" key={m}>
                  <span className="k">{m}</span>
                  <span className="v missing">Still needed</span>
                </div>
              ))}
            </div>
        </div>
      ))}
    </section>
  );
}
