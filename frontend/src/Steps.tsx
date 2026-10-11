/** Every step except documents is rendered straight from the field dictionary.
 *  Adding a field to the JSON adds it to the screen, with no change here. */
import { useEffect, useState } from "react";
import { Icon } from "./icons";
import { money, money2, num } from "./format";
import { Cards, Field, Segmented } from "./ui";
import type {
  Dictionary, FieldSpec, GroupSpec, Progress, RepeatableSpec, StepSpec, NameSuggestion, AddressSuggestion, EmploymentSuggestion,
} from "./types";

export interface Provenance { fileName: string; page: number | null; fileId: string }

export interface StepProps {
  employmentSuggestions: EmploymentSuggestion[];
  addressSuggestions: AddressSuggestion[];
  onChooseAddress: (candidate: AddressSuggestion) => void;
  accountName: string;
  nameSuggestions: NameSuggestion[];
  onChooseName: (candidate: NameSuggestion) => void;
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
        <div className="journey-start"><div><b>{props.accountName ? `Welcome, ${props.accountName}.` : "Choose your starting point"}</b><p>Answer a few questions, or upload your documents first and review any suggested answers.</p></div><button className="btn sec" onClick={() => props.onGo(1)}><Icon name="upload" />Start with documents</button></div>
      </>}
      {step.groups.some(g => g.fields?.some(n => props.provenance[n])) && <div className="prefill-notice"><Icon name="spark" /><div><b>A head start from your documents</b><p>Review the suggested details below. You can edit any answer or open its source.</p></div></div>}
      {step.groups.map((group, i) => (
        <Group key={`${step.id}-${i}`} group={group} {...props} />
      ))}
      {step.id === "review" && <Summary {...props} />}
    </>
  );
}

function NameSuggestions(props: StepProps) {
  const candidates = props.nameSuggestions;
  if (!candidates.length) return null;
  const normalise = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const different = new Set([...candidates.map(c => normalise(c.label)), normalise(props.accountName)].filter(Boolean)).size > 1;
  return <div className="name-suggestions">
    <details><summary><Icon name="user" /><span className="suggestion-title">{different ? "Review your name" : "Use a name from your documents"}</span><span className="suggestion-count">{candidates.length} sources</span></summary>
      <p>Choose your name or type it below. Documents may belong to different people.</p>
      <div className="name-candidates">{candidates.map(candidate => <div key={candidate.file_id} className="name-candidate">
        <div><b>{candidate.label}</b><small>{candidate.document_type} · {candidate.file_name}{candidate.page ? ` · page ${candidate.page}` : ""}</small>
        {(!candidate.first_name || !candidate.last_name) && <small>First and last names are not both available. Enter them below; we will not split this name.</small>}</div>
        <div className="name-actions"><button type="button" className="btn sec" onClick={() => props.onOpenSource(candidate.file_id)}>View source</button>
        <button type="button" className="btn" disabled={!candidate.first_name || !candidate.last_name} onClick={() => props.onChooseName(candidate)}>Use this name</button></div>
      </div>)}</div>
    </details>
    <small>Your choice is confirmed when you continue.</small>
  </div>;
}

function AddressSuggestions(props: StepProps) {
  const candidates = props.addressSuggestions;
  if (!candidates.length) return null;
  const different = new Set(candidates.map(c => c.label.toLowerCase().replace(/[^a-z0-9]/g, ""))).size > 1;
  return <div className="name-suggestions">
    <details><summary><Icon name="home" /><span className="suggestion-title">{different ? "Review your address" : "Use an address from your documents"}</span><span className="suggestion-count">{candidates.length} sources</span></summary>
      <p>Choose your current home address or type it below. Document addresses may be outdated.</p>
      <div className="name-candidates">{candidates.map(candidate => <div key={candidate.file_id} className="name-candidate">
        <div><b>{candidate.label}</b><small>{candidate.document_type} · {candidate.file_name}{candidate.page ? ` · page ${candidate.page}` : ""}</small>
        {(!candidate.address || !candidate.city || !candidate.state || !candidate.zip) && <small>Incomplete address. View the source and enter the missing details below.</small>}</div>
        <div className="name-actions"><button type="button" className="btn sec" onClick={() => props.onOpenSource(candidate.file_id)}>View source</button>
        <button type="button" className="btn" disabled={!candidate.address || !candidate.city || !candidate.state || !candidate.zip} onClick={() => props.onChooseAddress(candidate)}>Use this address</button></div>
      </div>)}</div>
    </details>
    <small>Your choice is confirmed when you continue.</small>
  </div>;
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

      {names.includes("addr1") && <AddressSuggestions {...props} />}
      {names.includes("firstName") && <NameSuggestions {...props} />}

      {plain.length > 0 && (
        <div className={`grid g2 ${names.includes("addr1") ? "address-grid" : ""}`}>
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

  const invalidIncome = kind === "employment" && list.filter(row => row.is_current !== false).some(row => ["base", "overtime", "bonuses", "commissions"].some(key => row[key] != null && String(row[key]).trim() !== "" && !/^(?:\$)?[\d,]+(?:\.\d{1,2})?$/.test(String(row[key]).trim())));
  const total = list.filter(row => row.is_current !== false).reduce((a, row) =>
    a + num(row.base) + num(row.overtime) + num(row.bonuses) + num(row.commissions), 0);

  return (
    <section className="card">
      <h2>{title}</h2>
      {spec.hint && <p className="hint">{spec.hint}</p>}

      {kind === "employment" && <DocumentEmployers {...props} list={list} />}
      {kind === "employment" && <EmploymentReview {...props} list={list} />}

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
          {kind === "employment" && <div className="employment-status">
            <label className="cap" htmlFor={`job-status-${index}`}>Employment status</label>
            <select className="ctl" id={`job-status-${index}`} value={row.is_current === false ? "previous" : "current"}
              onChange={e => onRows(kind, list.map((item, i) => i === index ? {...item, is_current: e.target.value === "current", ...(e.target.value === "current" ? {end_date: null} : {})} : item))}>
              <option value="current">Current job — include in monthly income</option><option value="previous">Previous job — employment history only</option>
            </select>
            {row.is_current === false && <div className="f"><label className="cap" htmlFor={`job-end-${index}`}>End date</label>
              <input type="date" className="ctl" id={`job-end-${index}`} value={String(row.end_date ?? "")} onChange={e => update(index, "end_date", e.target.value)} />
              <small>This job's income is excluded from the current monthly total.</small></div>}
          </div>}
          {kind === "employment" && row.is_current !== false && <IncomeSuggestions {...props} row={row} index={index} list={list} />}
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
                    {row[f.id] !== undefined && String(row[f.id]).trim() !== "" && !/^(?:\$)?[\d,]+(?:\.\d{1,2})?$/.test(String(row[f.id]).trim()) && <small role="alert" style={{color:"#b42318"}}>Enter a nonnegative monthly amount.</small>}
                    {kind === "employment" && f.id === "base" && row.is_current !== false && num(row[f.id]) <= 0 && <small style={{color:"#b42318"}}>Enter or review a positive monthly base income for this current job.</small>}
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
                    Monthly base amount from a {String(row.pay_frequency)} printed pay rate. Review it; period gross may contain additional earnings.
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
          <b>Total current monthly employment income</b><span className="amt">{invalidIncome ? "Review invalid amounts" : money2(total)}</span>
        </div>
      )}
    </section>
  );
}

const employerKey = (value: unknown) => String(value ?? "").trim().replace(/\s+/g, " ").toLowerCase();

function DocumentEmployers(props: StepProps & { list: Record<string, unknown>[] }) {
  const groups = [...new Set(props.employmentSuggestions.map(c => employerKey(c.employer_name)))];
  if (!groups.length) return null;
  return <details className="name-suggestions employer-suggestions"><summary><Icon name="folder" /><span className="suggestion-title">Employers from your documents</span><span className="suggestion-count">{groups.length} found</span></summary><p>Add a missing job here. Multiple documents can support the same job.</p>
    {groups.map(key => {
      const sources = props.employmentSuggestions.filter(c => employerKey(c.employer_name) === key);
      const candidate = sources[0];
      const exists = props.list.some(row => row.is_current !== false && employerKey(row.employer_name) === key);
      return <div className="name-candidate" key={key}><b>{candidate.employer_name}</b><small>{sources.length} supporting {sources.length === 1 ? "document" : "documents"}</small>
        {exists ? <span className="employer-added"><Icon name="check" />Added to your jobs</span> : <button className="btn sec" type="button" onClick={() => props.onRows("employment", [...props.list, {employer_name: candidate.employer_name, is_current: true, base: "", position: ""}])}><Icon name="plus" />Add job</button>}
      </div>;
    })}</details>;
}

function IncomeSuggestions(props: StepProps & { row: Record<string, unknown>; index: number; list: Record<string, unknown>[] }) {
  const candidates = props.employmentSuggestions.filter(c => c.document_type === "paystub" && employerKey(c.employer_name) === employerKey(props.row.employer_name));
  if (!candidates.length) return null;
  return <details className="name-suggestions"><summary>Review document income suggestions</summary>
    <p>Apply only the income for this job and person. Your position and start date will stay unchanged.</p>
    {candidates.map(c => <div className="name-candidate" key={c.file_id}><b>{c.base !== null ? `${money2(num(c.base))} base income per month` : "Base income needs review"}</b>
      <small>{c.employee_name || "Employee name unavailable"} · {c.file_name}{c.page ? ` · page ${c.page}` : ""}</small><small>{c.calculation}</small>{c.gross_pay && <small>Total gross for this period: {money2(num(c.gross_pay))} — may include additional earnings.</small>}
      <div className="name-actions"><button className="btn sec" type="button" onClick={() => props.onOpenSource(c.file_id)}>View source</button>
      <button className="btn" type="button" disabled={c.base === null} onClick={() => props.onRows("employment", props.list.map((row, i) => i === props.index ? {...row, base: c.base, pay_frequency: c.pay_frequency} : row))}>Use this base income</button>
      {c.position && <button className="btn sec" type="button" onClick={() => props.onRows("employment", props.list.map((row, i) => i === props.index ? {...row, position: c.position} : row))}>Use job title: {c.position}</button>}</div>
    </div>)}<small>Save and continue to confirm your choice. Income proposals are alternatives, not amounts to add together.</small>
  </details>;
}

function EmploymentReview(props: StepProps & { list: Record<string, unknown>[] }) {
  const [preview, setPreview] = useState<{ first: number; second: number; merged: Record<string, unknown> } | null>(null);
  useEffect(() => { setPreview(null); }, [props.list]);
  const pairs = props.list.flatMap((row, first) => props.list.flatMap((other, second) =>
    second > first && (row.is_current !== false) === (other.is_current !== false) && employerKey(row.employer_name) && employerKey(row.employer_name) === employerKey(other.employer_name) ? [{first, second}] : []));
  if (!pairs.length) return null;
  const start = (first: number, second: number) => {
    const merged = {...props.list[first]};
    for (const [key, value] of Object.entries(props.list[second])) if (merged[key] === null || merged[key] === undefined || merged[key] === "") merged[key] = value;
    setPreview({first, second, merged});
  };
  return <div className="name-suggestions duplicate-review"><div className="suggestion-warning"><Icon name="alert" /><div><b>Possible duplicate jobs</b><p>Check these entries before continuing. Current jobs both count toward income.</p></div></div>
    {pairs.map(pair => <button type="button" className="btn sec" key={`${pair.first}-${pair.second}`} onClick={() => start(pair.first, pair.second)}>Compare jobs {pair.first + 1} & {pair.second + 1}</button>)}
    {preview && <div className="name-candidate"><h3>Preview combined job</h3><p>Existing values are kept by default. Choose which conflicting details to keep. Amounts will not be added together.</p>
      {props.dictionary.repeatables.employment.fields.map(field => {
        const a = String(props.list[preview.first]?.[field.id] ?? ""), b = String(props.list[preview.second]?.[field.id] ?? "");
        return <div className="f" key={field.id}><label className="cap">{field.label}</label>{a && b && a !== b ?
          <select className="ctl" aria-label={`Keep ${field.label}`} value={String(preview.merged[field.id] ?? "")} onChange={e => setPreview({...preview, merged: {...preview.merged, [field.id]: e.target.value, ...(field.id === "base" ? {pay_frequency: props.list[e.target.value === b ? preview.second : preview.first].pay_frequency} : {})}})}>
            <option value={a}>Entry {preview.first + 1}: {a}</option><option value={b}>Entry {preview.second + 1}: {b}</option>
          </select> : <p>{String(preview.merged[field.id] ?? "") || "Not entered"}</p>}</div>;
      })}
      <div className="name-actions"><button type="button" className="btn" onClick={() => {props.onRows("employment", props.list.flatMap((row, i) => i === preview.second ? [] : [i === preview.first ? {...preview.merged, source_file_id: null} : row])); setPreview(null);}}>Combine these entries</button>
      <button type="button" className="btn sec" onClick={() => setPreview(null)}>Keep separate jobs</button></div><small>Save and continue to persist the combined entry. Documents remain in your vault.</small>
    </div>}
  </div>;
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
