/** Shell and state. Sign-in lands on the vault; an application is opened from there and saved on every step. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, auth, ApiError } from "./api";
import { AuthPage } from "./AuthPage";
import type { CustomerProfile } from "./api";
import { TemplateDocuments } from "./TemplateDocuments";
import { ChatScope, DocumentChat } from "./DocumentChat";
import { DocDrawer } from "./DocDrawer";
import { DocumentsStep, DOCUMENTS_LEDE } from "./Documents";
import { validate } from "./format";
import { Icon } from "./icons";
import { FormStep, type Provenance } from "./Steps";
import { FootNav, Rail, StepHero, useToast } from "./ui";
import { SendDocument } from "./SendDocument";
import { LenderInvitation } from "./LenderInvitation";
import { VaultHome } from "./VaultHome";
import type {
  ApplicationListItem, ApplicationState, ChecklistItem, Dictionary, DocumentSummary, Progress, NameSuggestion, AddressSuggestion, EmploymentSuggestion,
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
  const [vaultOpen, setVaultOpen] = useState(true);
  const [applications, setApplications] = useState<ApplicationListItem[]>([]);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatStarted, setChatStarted] = useState(false);
  const [chatUnread, setChatUnread] = useState(false);
  const [vaultChatApp, setVaultChatApp] = useState<string | null>(null);
  const [templateOpen,setTemplateOpen] = useState(false);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [user, setUser] = useState<CustomerProfile | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const email = user?.email || "";
  useEffect(() => {
    const expired = () => { setUser(null); setAppId(null); setDictionary(null); setValues({}); setDocuments([]); setNameSuggestions([]); setAddressSuggestions([]); setEmploymentSuggestions([]); setProvenance({}); setDeclarations({}); setRows({employment:[],asset:[],liability:[]}); setCustomerId(null); setProgress(null); setVaultDocuments([]); setApplications([]); setVaultOpen(true); dirty.current = false; setUnsaved(false); };
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
        const [dict, list, apps, docs] = await Promise.all([api.dictionary(), api.checklist(), api.listApplications(), api.documents()]);
        setDictionary(dict);
        setChecklist(list);
        setApplications(apps);
        setVaultDocuments(docs);
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "We could not open your vault.");
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

  /** The vault page: every document the customer has, and their applications. */
  const refreshVault = useCallback(async () => {
    const [docs, apps] = await Promise.all([api.documents(), api.listApplications()]);
    setVaultDocuments(docs); setApplications(apps);
  }, []);

  /** Open an application from the vault. Nothing from the previous one carries over. */
  async function openApplication(id: string, at = 0) {
    dirty.current = false; setUnsaved(false); setErrors({}); setSaveError(""); setJustSaved(false);
    setChatOpen(false); setChatStarted(false); setChatUnread(false); setSubmitted(null);
    try {
      await load(id);
      setAppId(id); setStep(Math.min(Math.max(0, at), (dictionary?.steps.length ?? 1) - 1)); setVaultOpen(false);
      window.scrollTo({ top: 0 });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "We could not open this application.");
    }
  }

  async function showVault() {
    if (dirty.current && !(await save())) return;
    setVaultOpen(true);
    window.scrollTo({ top: 0 });
    void refreshVault().catch(() => {});
  }

  /** Reload whatever is on screen after a document changes. */
  const refresh = () => { if (appId && !vaultOpen) void load(appId).catch(() => {}); else void refreshVault().catch(() => {}); };

  /* --------------------------------------------- poll while docs process */
  useEffect(() => {
    const busy = (docs: DocumentSummary[]) => docs.some((d) => d.status === "queued" || d.status === "processing");
    const inApp = !!appId && !vaultOpen;
    if (inApp ? !busy(documents) : !busy(vaultDocuments)) return;
    const timer = setInterval(() => {
      if (inApp && appId) void load(appId).catch(() => {}); else void refreshVault().catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [documents, vaultDocuments, appId, vaultOpen, load, refreshVault]);

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
        const missing = err instanceof ApiError ? ((err.detail as {detail?: {missing?: string[]}} | null)?.detail?.missing ?? []) : [];
        toast(missing.length ? `Before you submit, we still need: ${missing.slice(0, 6).join(", ")}${missing.length > 6 ? ` and ${missing.length - 6} more` : ""}.`
          : err instanceof ApiError ? err.message : "We could not submit the application.");
      }
      return;
    }
    goTo(step + 1);
  }

  async function goTo(i: number) {
    if (dirty.current && !(await save())) return;
    // Remember where they are, so reopening the application lands here and not one step back.
    if (appId && i !== step && applications.some(a => a.application_id === appId && a.status === "draft")) void api.patchApplication(appId, { current_step: i }).catch(() => {});
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

  if (!dictionary) {
    return <div className="body"><main className="main"><p className="lede">Opening your vault…</p></main></div>;
  }
  const inApplication = !vaultOpen && !!appId && !!stepSpec;
  // Chat is customer chat on both pages (Vijay, Oct 2026). Inside an application it answers from that application's
  // documents. On the vault page from the one chosen, else the last opened, else the newest; with no application,
  // or when the customer picks "All documents in my vault" (""), from the whole vault (null).
  const known = (id: string | null) => !!id && applications.some(a => a.application_id === id);
  const chatAppId: string | null = inApplication ? appId : vaultChatApp === "" ? null : known(vaultChatApp) ? vaultChatApp : known(appId) ? appId : applications[0]?.application_id ?? null;

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
            <button className="btn" style={{ marginTop: 18 }} onClick={() => { setSubmitted(null); setAppId(null); setVaultOpen(true); void refreshVault().catch(() => {}); }}>
              <Icon name="folder" />Back to my vault
            </button>
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
          {inApplication ? <button className="ghost" onClick={() => void showVault()}><Icon name="folder" /><span>My vault</span></button>
            : appId && applications.some(a => a.application_id === appId && a.status === "draft") && <button className="ghost" onClick={() => void openApplication(appId, step)}><Icon name="home" /><span>Back to application</span></button>}
          <details className="header-menu" ref={notificationMenu} onToggle={e => { if (e.currentTarget.open && profileMenu.current) profileMenu.current.open = false; }}>
            <summary aria-label="Notifications"><Icon name="bell" /></summary>
            <section className="header-popover" aria-label="Application notifications">
              <h2>{inApplication ? "Application updates" : "Vault updates"}</h2>
              {inApplication ? <>
                <p>{unsaved ? "You have unsaved answers. Save and continue to keep your progress." : "Your latest application answers are saved."}</p>
                <p>{documents.length ? `${documents.length} document${documents.length === 1 ? "" : "s"} attached to your application. Open My vault to review their status.` : "No documents uploaded yet. Visit Documents to see what to provide."}</p>
              </> : <>
                <p>{vaultDocuments.length ? `${vaultDocuments.length} document${vaultDocuments.length === 1 ? "" : "s"} saved in your vault.` : "Your vault is empty. Add a document to keep it safe here."}</p>
                <p>{applications.some(a => a.status === "draft") ? "You have an application in progress. Continue it from the top of your vault." : "No application yet. When your loan officer invites you, open the link in their email to start one."}</p>
              </>}
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
              {inApplication && appId && (() => {
                const reference = `HF-${appId.replaceAll("-", "").slice(0, 8).toUpperCase()}`;
                return (
                  <div className="profile-app-id">
                    <span><small>Application ID</small><strong>{reference}</strong></span>
                    <button type="button" onClick={async () => {
                      try { await navigator.clipboard.writeText(reference); toast("Application ID copied", "ok"); }
                      catch { toast(`Could not copy. Your application ID is ${reference}.`); }
                    }}><Icon name="copy" />Copy</button>
                  </div>
                );
              })()}
              {inApplication && <button className="profile-action" onClick={e => { e.currentTarget.closest("details")?.removeAttribute("open"); void goTo(2); }}><Icon name="user" /><span>Personal information</span><Icon name="chevron" /></button>}
              <button className="profile-action" onClick={e => { e.currentTarget.closest("details")?.removeAttribute("open"); void showVault(); }}><Icon name="folder" /><span>My vault</span><Icon name="chevron" /></button>
              {inApplication && <button className="profile-action" onClick={async e=>{const menu=e.currentTarget.closest("details");if(dirty.current&&!(await save()))return;menu?.removeAttribute("open");setTemplateOpen(true);}}><Icon name="doc"/><span>Generate document (POC)</span><Icon name="chevron"/></button>}
              <button className="profile-action logout" onClick={async () => { if (dirty.current && !(await save())) return; try { await auth.logout(); window.location.reload(); } catch { toast("Could not log out. Please try again."); } }}><Icon name="logout" /><span>Log out</span></button>
            </section>
          </details>
        </div>
      </header>


      <div className={`body ${inApplication ? "" : "vault-body"}`}>
        {inApplication && <Rail dictionary={dictionary} progress={progress} step={step} onGo={goTo} />}
        <main className="main" ref={main} tabIndex={-1}>
          <LenderInvitation onAccepted={id=>{void refreshVault();void openApplication(id,0);}} />
          {!inApplication || !appId || !stepSpec ? (
            <VaultHome firstName={user.first_name || undefined} documents={vaultDocuments} applications={applications}
                       onOpen={setOpenDoc} onChanged={() => void refreshVault().catch(() => {})}
                       onContinue={a => void openApplication(a.application_id, a.current_step ?? 0)} />
          ) : <>
          <p className="application-title">My Loan Application · {`HF-${appId.replaceAll("-", "").slice(0, 8).toUpperCase()}`}</p>
          {stepSpec.id === "documents" ? (
            <>{progress?.status === "submitted" ? <section className="card"><h2>Submitted documents</h2>
              {documents.map(doc => <p key={doc.file_id}><a href={doc.submitted_copy ? api.submittedContentUrl(appId, doc.file_id) : api.contentUrl(doc.file_id)}>{doc.original_name}</a></p>)}
              {!documents.length && <p>No documents attached.</p>}
            </section> : <DocumentsStep applicationId={appId} checklist={checklist.map(c => ["Self-employed", "Retired", "Not currently employed", "Other"].includes(values.employmentStatus) && ["w2", "paystub"].includes(c.document_tag) ? { ...c, required_count: 0, guidance: "Optional for your current employment situation. You can still upload this document if it applies to you." } : c)} documents={documents} vaultDocuments={vaultDocuments}
                           header={<StepHero dictionary={dictionary} step={step} title="Your documents" lede={DOCUMENTS_LEDE} />}
                           onUploaded={() => void load(appId)} onOpenDoc={setOpenDoc} />}<SendDocument key={appId} app={appId} documents={documents} /></>
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
          <FootNav step={step} lastStep={step === dictionary.steps.length - 1}
               blocking={blocking} busy={busy} unsaved={unsaved} justSaved={justSaved} saveError={saveError}
               onBack={() => goTo(Math.max(0, step - 1))} onNext={() => void next()} />
          </>}
        </main>
      </div>

      {!chatOpen && !openDoc && <button className="assistant-launcher" type="button" aria-label={chatUnread ? "New reply from HomeFlow - open chat" : chatStarted ? "Resume HomeFlow conversation" : "Ask HomeFlow about your documents"} onClick={() => {setChatStarted(true);setChatOpen(true);setChatUnread(false);}}><Icon name="chat" /><span className="assistant-launcher-label">{chatUnread ? "New reply" : chatStarted ? "Resume chat" : "Ask HomeFlow"}</span>{chatUnread ? <span className="chat-unread-badge" role="status" aria-label="Unread reply">1</span> : chatStarted && <span className="chat-active-dot" aria-label="Conversation active" />}</button>}
      {templateOpen && appId && <TemplateDocuments applicationId={appId} onClose={()=>setTemplateOpen(false)}/>}
      {chatStarted && <DocumentChat key={chatAppId ?? "vault"} applicationId={chatAppId} owner={user.customer_id} minimized={!chatOpen || !!openDoc}
        onUnread={() => setChatUnread(true)} onClose={() => setChatOpen(false)} onOpenSource={setOpenDoc}
        onUpload={() => { const documentsStep = dictionary.steps.findIndex(s => s.id === "documents");
          if (inApplication && documentsStep >= 0) void goTo(documentsStep); else window.dispatchEvent(new Event("homeflow:upload")); }}
        scope={inApplication ? undefined : <ChatScope applications={applications} value={chatAppId ?? ""} onChange={setVaultChatApp} />} />}
      <DocDrawer fileId={openDoc} onClose={() => setOpenDoc(null)}
                 onSaved={refresh} />
    </div>
  );
}
