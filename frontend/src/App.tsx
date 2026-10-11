/** Shell and state. One application, loaded from the API, saved on every step. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, auth, ApiError } from "./api";
import { AuthPage } from "./AuthPage";
import type { CustomerProfile } from "./api";
import { DocumentChat } from "./DocumentChat";
import { DocDrawer } from "./DocDrawer";
import { DocCard, DocumentsStep } from "./Documents";
import { validate } from "./format";
import { Icon } from "./icons";
import { FormStep, type Provenance } from "./Steps";
import { FootNav, Rail, useToast } from "./ui";
import type {
  ApplicationState, ChecklistItem, Dictionary, DocumentSummary, Progress, NameSuggestion, AddressSuggestion, EmploymentSuggestion,
} from "./types";

type Rows = Record<string, Record<string, unknown>[]>;

export function App() {
  const [dictionary, setDictionary] = useState<Dictionary | null>(null);
  const [checklist, setChecklist] = useState<ChecklistItem[]>([]);
  const [appId, setAppId] = useState<string | null>(null);
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [employmentSuggestions, setEmploymentSuggestions] = useState<EmploymentSuggestion[]>([]);
  const [addressSuggestions, setAddressSuggestions] = useState<AddressSuggestion[]>([]);
  const [nameSuggestions, setNameSuggestions] = useState<NameSuggestion[]>([]);
  const [provenance, setProvenance] = useState<Record<string, Provenance>>({});
  const [declarations, setDeclarations] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<Rows>({ employment: [], asset: [], liability: [] });
  const [vaultDocuments, setVaultDocuments] = useState<DocumentSummary[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [vaultOpen, setVaultOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [user, setUser] = useState<CustomerProfile | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const email = user?.email || "";
  useEffect(() => {
    const expired = () => { setUser(null); setAppId(null); setDictionary(null); setValues({}); setDocuments([]); setNameSuggestions([]); setAddressSuggestions([]); setEmploymentSuggestions([]); setProvenance({}); setDeclarations({}); setRows({employment:[],asset:[],liability:[]}); setCustomerId(null); setProgress(null); dirty.current = false; setUnsaved(false); };
    window.addEventListener("homeflow:session-expired", expired);
    if (location.hash.startsWith("#reset=")) setAuthChecked(true);
    else void auth.me().then(setUser).catch(() => setUser(null)).finally(() => setAuthChecked(true));
    return () => window.removeEventListener("homeflow:session-expired", expired);
  }, []);
  const toast = useToast();
  const main = useRef<HTMLElement>(null);
  const notificationMenu = useRef<HTMLDetailsElement>(null);
  const profileMenu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const menus = () => [notificationMenu.current, profileMenu.current];
    const dismissOutside = (event: PointerEvent) => {
      if (menus().some(menu => menu?.contains(event.target as Node))) return;
      menus().forEach(menu => { if (menu) menu.open = false; });
    };
    const dismissEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const openMenu = menus().find(menu => menu?.open);
      if (openMenu) { openMenu.open = false; openMenu.querySelector("summary")?.focus(); }
    };
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("keydown", dismissEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("keydown", dismissEscape);
    };
  }, []);
  const dirty = useRef(false);
  const [unsaved, setUnsaved] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [justSaved, setJustSaved] = useState(false);
  useEffect(() => {
    if (!justSaved) return;
    const timer = window.setTimeout(() => setJustSaved(false), 4000);
    return () => window.clearTimeout(timer);
  }, [justSaved]);
  function markDirty() { dirty.current = true; setUnsaved(true); setJustSaved(false); }

  /* ---------------------------------------------------------- bootstrap */
  useEffect(() => {
    if (!user) return;
    void (async () => {
      try {
        const [dict, list] = await Promise.all([api.dictionary(), api.checklist()]);
        setDictionary(dict);
        setChecklist(list);
        const existing = await api.listApplications();
        const draft = existing.find((a) => a.status === "draft");
        const id = draft?.application_id ?? (await api.createApplication()).application_id;
        setAppId(id);
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "We could not start your application.");
      }
    })();
  }, [toast, user]);

  const load = useCallback(async (id: string) => {
    const [state, prog, docs, vaultDocs] = await Promise.all([
      api.getApplication(id), api.progress(id), api.documents(id), api.documents(),
    ]);
    setNameSuggestions(state.name_suggestions ?? []);
    setAddressSuggestions(state.address_suggestions ?? []);
    setEmploymentSuggestions(state.employment_suggestions ?? []);
    if (!dirty.current) applyState(state, docs);
    setProgress(prog);
    setDocuments(docs);setVaultDocuments(vaultDocs);
  }, []);

  function applyState(state: ApplicationState, sourceDocs: DocumentSummary[] = documents) {
    setCustomerId(state.customer_id ?? null);
    const next: Record<string, string> = {};
    const prov: Record<string, Provenance> = {};
    for (const [name, field] of Object.entries(state.fields)) {
      next[name] = field.value ?? "";
      if (field.review_state === "proposed" && field.file_id) {
        prov[name] = { fileName: sourceDocs.find(d => d.file_id === field.file_id)?.display_name ?? "Document", page: field.page, fileId: field.file_id };
      }
    }
    setValues(next);
    setProvenance(prov);
    setDeclarations(state.declarations);
    setRows({
      employment: state.employment, asset: state.asset, liability: state.liability,
    });
  }

  useEffect(() => { if (appId) void load(appId).catch(() => {}); }, [appId, load]);

  /* --------------------------------------------- poll while docs process */
  useEffect(() => {
    const pending = documents.some((d) => d.status === "queued" || d.status === "processing");
    if (!pending || !appId) return;
    const timer = setInterval(() => { void load(appId).catch(() => {}); }, 4000);
    return () => clearInterval(timer);
  }, [documents, appId, load]);

  /* --------------------------------------------------------- field edits */
  const setValue = (name: string, value: string) => {
    markDirty();
    setValues((v) => ({ ...v, [name]: value }));
    setProvenance((p) => {
      if (!p[name]) return p;
      const next = { ...p };
      delete next[name];              // their edit, their value from now on
      return next;
    });
    if (errors[name]) setErrors((e) => ({ ...e, [name]: "" }));
  };

  const blurField = (name: string) => {
    if (!dictionary) return;
    const spec = dictionary.fields[name];
    if (!spec) return;
    setErrors((e) => ({ ...e, [name]: validate(spec, values[name]) }));
  };

  async function save(): Promise<boolean> {
    if (!appId) return false;
    setBusy(true); setSaveError(""); setJustSaved(false);
    try {
      await api.patchApplication(appId, {
        fields: values, declarations, current_step: step,
        employment: rows.employment, asset: rows.asset, liability: rows.liability,
      });
      dirty.current = false; setUnsaved(false); setJustSaved(true);
      try { setProgress(await api.progress(appId)); } catch { /* Answers were saved; progress can refresh later. */ }
      return true;
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "We could not save your changes.";
      setSaveError(message); toast(message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const stepSpec = dictionary?.steps[step];
  const blocking = useMemo(() => {
    const state = progress?.steps[step];
    if (!state || state.complete || !state.missing.length) return null;
    return state.missing.length > 3
      ? `${state.missing.length} answers still needed`
      : `Still needed: ${state.missing.join(", ")}`;
  }, [progress, step]);

  async function next() {
    if (!dictionary || !appId) return;
    const saved = await save();
    if (!saved) return;

    const fresh = await api.progress(appId);
    setProgress(fresh);
    const state = fresh.steps[step];

    if (state && !state.complete) {
      const local: Record<string, string> = {};
      for (const [name, spec] of Object.entries(dictionary.fields)) {
        if (spec.step === stepSpec?.id && (!spec.visible_if || values[spec.visible_if.field] === spec.visible_if.equals)) local[name] = validate(spec, values[name]);
      }
      setErrors(local);
      const firstBad = Object.entries(local).find(([, msg]) => msg)?.[0];
      if (firstBad) {
        const el = document.getElementById(`f_${firstBad}`);
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(() => el?.focus(), 300);
      } else {
        toast(state.missing.join(", "));
      }
      return;
    }

    if (step === dictionary.steps.length - 1) {
      try {
        const result = await api.submit(appId);
        setSubmitted(result.reference);
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "We could not submit the application.");
      }
      return;
    }
    goTo(step + 1);
  }

  async function goTo(i: number) {
    if (dirty.current && !(await save())) return;
    setStep(i);
    setVaultOpen(false);
    requestAnimationFrame(() => {
      const section = main.current;
      if (!section) return;
      window.scrollTo({ top: Math.max(0, section.getBoundingClientRect().top + window.scrollY - 110), behavior: "smooth" });
      section.focus({ preventScroll: true });
    });
  }

  /* ------------------------------------------------------------- sign in */
  if (!authChecked) return <main className="main"><p>Checking your session…</p></main>;
  if (!user) return <AuthPage onAuthenticated={profile => { setUser(profile); setCustomerId(profile.customer_id); }} />;

  if (!dictionary || !appId || !stepSpec) {
    return <div className="body"><main className="main"><p className="lede">Loading your application…</p></main></div>;
  }

  if (submitted) {
    return (
      <div className="body">
        <main className="main">
          <section className="card" style={{ textAlign: "center", padding: "44px 22px" }}>
            <div style={{ width: 64, height: 64, borderRadius: "50%", background: "var(--good-soft)",
                          color: "var(--good)", display: "grid", placeItems: "center", margin: "0 auto 18px" }}>
              <span style={{ display: "block", width: 30, height: 30 }}><Icon name="check" width={3} /></span>
            </div>
            <h1 className="h1" style={{ fontSize: 26 }}>
              Thanks, {values.firstName || "there"}. Your application is in.
            </h1>
            <p className="lede" style={{ maxWidth: "48ch", margin: "10px auto 0" }}>
              A loan officer picks it up from here. We will email you if anything we read from your
              documents needs a second look, and your documents stay in your vault.
            </p>
            <p className="hint" style={{ marginTop: 22 }}>Reference {submitted}</p>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-in">
          <div className="brand">
            <span className="mark" aria-hidden="true"><Icon name="homeflow" /></span>
            <span>HomeFlow<small>Your path home</small></span>
          </div>
          <div className="spacer" />
          <button className="ghost" onClick={async () => { if (dirty.current && !(await save())) return; setVaultOpen((v) => !v); }}>
            <Icon name="folder" /><span>{vaultOpen ? "Back to application" : "My vault"}</span>
          </button>
          <details className="header-menu" ref={notificationMenu} onToggle={e => { if (e.currentTarget.open && profileMenu.current) profileMenu.current.open = false; }}>
            <summary aria-label="Notifications"><Icon name="bell" /></summary>
            <section className="header-popover" aria-label="Application notifications">
              <h2>Application updates</h2>
              <p>{unsaved ? "You have unsaved answers. Save and continue to keep your progress." : "Your latest application answers are saved."}</p>
              <p>{documents.length ? `${documents.length} document${documents.length === 1 ? "" : "s"} attached to your application. Open My vault to review their status.` : "No documents uploaded yet. Visit Documents to see what to provide."}</p>
            </section>
          </details>
          <details className="header-menu profile-menu" ref={profileMenu} onToggle={e => { if (e.currentTarget.open && notificationMenu.current) notificationMenu.current.open = false; }}>
            <summary aria-label="Your profile"><span className="avatar">{(user.first_name || email || "H").slice(0, 2).toUpperCase()}</span></summary>
            <section className="header-popover" aria-label="Your profile">
              <details className="profile-overview">
                <summary><span className="profile-symbol"><Icon name="user" /></span><span><small>Your account</small><strong>Your profile</strong></span><Icon name="chevron" /></summary>
                <div className="profile-details">
                  <p className="profile-name">{[user.first_name, user.last_name].filter(Boolean).join(" ") || "Name not entered yet"}</p>
                  <p className="profile-email">{email}</p>
                  <div className="profile-account-reference"><small>Account reference</small><p className="profile-reference">{customerId || user.customer_id}</p></div>
                </div>
              </details>
              <button className="profile-action" onClick={e => { e.currentTarget.closest("details")?.removeAttribute("open"); void goTo(2); }}><Icon name="user" /><span>Personal information</span><Icon name="chevron" /></button>
              <button className="profile-action" onClick={async e => { const menu = e.currentTarget.closest("details"); if (dirty.current && !(await save())) return; setVaultOpen(true); menu?.removeAttribute("open"); }}><Icon name="folder" /><span>My vault</span><Icon name="chevron" /></button>
              <button className="profile-action logout" onClick={async () => { if (dirty.current && !(await save())) return; try { await auth.logout(); window.location.reload(); } catch { toast("Could not log out. Please try again."); } }}><Icon name="logout" /><span>Log out</span></button>
            </section>
          </details>
        </div>
      </header>


      <div className="body">
        <Rail dictionary={dictionary} progress={progress} step={step} applicationId={appId} onGo={goTo} />
        <main className="main" ref={main} tabIndex={-1}>
          <p className="application-title">{vaultOpen ? "HomeFlow · Document library" : "My Loan Application"}</p>
          {vaultOpen ? (
            <Vault documents={vaultDocuments} onOpen={setOpenDoc} applicationId={appId} onChanged={() => void load(appId)} />
          ) : stepSpec.id === "documents" ? (
            <DocumentsStep applicationId={appId} checklist={checklist.map(c => ["Self-employed", "Retired", "Not currently employed", "Other"].includes(values.employmentStatus) && ["w2", "paystub"].includes(c.document_tag) ? { ...c, required_count: 0, guidance: "Optional for your current employment situation. You can still upload this document if it applies to you." } : c)} documents={documents} vaultDocuments={vaultDocuments}
                           onUploaded={() => void load(appId)} onOpenDoc={setOpenDoc} />
          ) : (
            <FormStep dictionary={dictionary} step={stepSpec} values={values} errors={errors}
                      provenance={provenance} declarations={declarations} rows={rows}
                      employmentSuggestions={employmentSuggestions}
                      addressSuggestions={addressSuggestions} onChooseAddress={candidate => {
                        setValue("addr1", candidate.address); setValue("city", candidate.city);
                        setValue("state", candidate.state); setValue("zip", candidate.zip);
                        toast("Address selected. Review it and save to confirm your current residence.");
                      }}
                      accountName={[user.first_name, user.last_name].filter(Boolean).join(" ")}
                      nameSuggestions={nameSuggestions} onChooseName={candidate => {
                        setValue("firstName", candidate.first_name);
                        setValue("lastName", candidate.last_name);
                        setValue("legalName", candidate.full_name || candidate.label);
                        toast("Name selected. Save and continue to confirm it. Review other document details too.");
                      }}
                      progress={progress} onGo={goTo}
                      onChange={setValue} onBlur={blurField}
                      onDeclaration={(code, answer) => { markDirty(); setDeclarations((d) => ({ ...d, [code]: answer })); }}
                      onRows={(kind, next) => { markDirty(); setRows((r) => ({ ...r, [kind]: next })); }}
                      onOpenSource={setOpenDoc} />
          )}
          {!vaultOpen && <FootNav step={step} lastStep={step === dictionary.steps.length - 1}
               blocking={blocking} busy={busy} unsaved={unsaved} justSaved={justSaved} saveError={saveError}
               onBack={() => goTo(Math.max(0, step - 1))} onNext={() => void next()} />}
        </main>
      </div>



      {!chatOpen && !openDoc && <button className="assistant-launcher" type="button" aria-label="Ask HomeFlow about your documents" onClick={() => setChatOpen(true)}><Icon name="chat" /><span className="assistant-launcher-label">Ask HomeFlow</span></button>}
      {chatOpen && <DocumentChat key={appId} applicationId={appId} onClose={() => setChatOpen(false)} onOpenSource={setOpenDoc} />}
      <DocDrawer fileId={openDoc} onClose={() => setOpenDoc(null)}
                 onSaved={() => void load(appId)} />
    </div>
  );
}

function Vault({ documents, onOpen, applicationId, onChanged }: {
  documents: DocumentSummary[]; onOpen: (id: string) => void; applicationId: string; onChanged: () => void;
}) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const tags = Array.from(new Set(documents.map((d) => d.document_tag)));
  const shown = documents.filter(d => (filter === "all" || d.document_tag === filter) && `${d.original_name} ${d.display_name}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <>
      <p className="eyebrow">Your vault</p>
      <h1 className="h1">My vault</h1>
      <p className="lede">
        All documents in your customer account, across applications. Select a document to review its details.
      </p>
      <div className="f" style={{ marginTop: 22 }}>
        <label className="cap" htmlFor="vault-search">Find a document</label>
        <input id="vault-search" className="ctl" type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by file name or document type" />
      </div>
      <div className="filters">
        <button className={`fchip ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>
          All ({documents.length})
        </button>
        {tags.map((t) => (
          <button key={t} className={`fchip ${filter === t ? "on" : ""}`} onClick={() => setFilter(t)}>
            {documents.find((d) => d.document_tag === t)?.display_name}{" "}
            ({documents.filter((d) => d.document_tag === t).length})
          </button>
        ))}
      </div>
      {shown.length ? (
        <div className="vaultgrid">
          {[{label:"Identity",tags:["drivers_license","ssn_card"]},{label:"Income",tags:["w2","paystub"]},{label:"Banking",tags:["bank_statement"]},{label:"Other documents",tags:tags.filter(t => !["drivers_license","ssn_card","w2","paystub","bank_statement"].includes(t))}].map(group => { const items = shown.filter(d => group.tags.includes(d.document_tag)); return items.length ? <section className="vault-group" key={group.label}><h2>{group.label}<span>{items.length}</span></h2><div className="vault-group-grid">{items.map(d => <DocCard key={d.file_id} doc={d} onOpen={onOpen} mode="vault" applicationId={applicationId} onChanged={onChanged} />)}</div></section> : null; })}
        </div>
      ) : (
        <section className="card">
          <p className="hint">
            {documents.length ? "No documents match your search. Try another name or type." : "Nothing here yet. Upload documents in the Documents section to see them here."}
          </p>
        </section>
      )}
    </>
  );
}



