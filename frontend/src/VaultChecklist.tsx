/** The vault page's pieces: the welcome block with New application and your applications, the folder
 *  list, and the documents list with its dark header, filters, review strip and one Actions menu per document. */
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { api, ApiError } from "./api";
import { applicationsOf, isIn } from "./Documents";
import { FOLDER_ICON, Icon } from "./icons";
import { useToast } from "./ui";
import { LOAN_KINDS, LOAN_TYPES, purposeName, reference, STORED_KINDS, vault, type ChecklistRow } from "./vault";
import type { ApplicationListItem, DocumentSummary, VaultFolder } from "./types";

export const BUSY = ["uploaded", "queued", "processing"];
const TONE: Record<string, string> = {
  Legal: "legal", "Identification & Licenses": "ids", "People & Places": "people", Finances: "finances",
  Taxes: "taxes", "Insurance & Property": "insurance", Other: "other",
};
export const tone = (folder?: string | null) => TONE[folder ?? "Other"] ?? "other";
const day = (iso?: string | null) => iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";

/** A document HomeFlow wants the customer to look at: unreadable, saved as Other against their choice,
 *  a type we can suggest, or several documents in one file. */
export const needsLook = (d: DocumentSummary) => d.status === "failed" || (d.status === "completed" && !!d.classification && (
  d.classification.mixed_document || (d.document_tag === "other" && d.classification.outcome === "mismatched"
    && (d.classification.selected_type !== "other" || LOAN_TYPES.includes(d.classification.detected_type)))));

/** Ready: a loan document that was read. Reading: still being read. Saved: stored and searchable. Needs review: something to check. */
export type Status = "ready" | "reading" | "saved" | "review";
export function statusOf(d: DocumentSummary): Status {
  if (BUSY.includes(d.status)) return "reading";
  if (needsLook(d)) return "review";
  return LOAN_TYPES.includes(d.document_tag) ? "ready" : "saved";
}
export const STATUS_LABEL: Record<Status, string> = { ready: "Ready", reading: "Reading", saved: "Saved", review: "Needs review" };

const ART = (
  <svg className="vs-art" viewBox="0 0 560 220" aria-hidden="true" fill="none" stroke="rgba(255,255,255,.78)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="250" cy="92" r="88" fill="#c9f27b" stroke="none" opacity=".22" /><path d="M10 190h540" /><path d="M60 198h330" opacity=".4" />
    <path d="M200 190V100l200-38v128" /><path d="M230 95v-20l150-28v48" /><path d="M400 62v128" /><path d="M400 82h46v108" />
    <rect x="226" y="120" width="44" height="70" /><path d="M248 120v70" /><path d="M262 152v6" /><path d="M300 120h80v40h-80z" opacity=".6" />
    <path d="M340 120v40" opacity=".6" /><circle cx="90" cy="98" r="28" /><path d="M90 126v64" /><path d="M90 150l-12-12M90 140l12-10" />
    <path d="M128 190c-6-10 0-24 12-22 2-10 18-12 22-2 10-4 18 6 14 14 6 4 4 10 0 10" /><path d="M300 190c-4-10 4-20 14-16 4-10 20-8 22 2 10-2 14 8 10 14" />
    <path d="M470 190l-14-40M478 190l-2-46M486 190l12-42M480 190l24-30M474 190l-24-30M482 190l-6-52" />
  </svg>
);

/* ------------------------------------------------------------ welcome block */
interface WelcomeProps {
  firstName?: string; applications: ApplicationListItem[]; lists: Record<string, ChecklistRow[]>; creating: boolean;
  onCreate: () => void; onContinue: (app: ApplicationListItem) => void; onDeleted: () => void;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

/** The top of the vault: a greeting, New application beside it, and one small pill per application. */
export function Welcome({ firstName, applications, lists, creating, onCreate, onContinue, onDeleted }: WelcomeProps) {
  const [deleting, setDeleting] = useState<ApplicationListItem | null>(null);
  return (
    <section className="vs-welcome" aria-labelledby="vs-hello">
      <div className="vs-welcome-copy">
        <p className="vs-ey">Your vault</p>
        <div className="vs-greet">
          <h1 id="vs-hello">{greeting()}{firstName ? `, ${firstName}` : ""}</h1>
          <button type="button" className="vs-newapp" onClick={onCreate} disabled={creating}>
            <span className="vs-newapp-ic"><Icon name="plus" /></span><span>{creating ? "Starting…" : "New application"}</span>
          </button>
        </div>
        {applications.length > 0 && <div className="vs-apps">
          <h2 id="vs-apps-title">Your applications</h2>
          <ul className="vs-pills" aria-labelledby="vs-apps-title">
            {applications.map(a => <AppPill key={a.application_id} app={a} rows={lists[a.application_id]} onContinue={onContinue} onDelete={() => setDeleting(a)} />)}
          </ul>
        </div>}
      </div>
      {ART}
      {deleting && <DeleteDraft app={deleting} onClose={() => setDeleting(null)} onDeleted={onDeleted} />}
    </section>
  );
}

function AppPill({ app, rows, onContinue, onDelete }: { app: ApplicationListItem; rows?: ChecklistRow[]; onContinue: (a: ApplicationListItem) => void; onDelete: () => void }) {
  const total = rows?.length ?? 5;
  const ready = rows ? rows.filter(r => r.have >= r.need).length : 0;
  const draft = app.status === "draft";
  return (
    <li className="vs-pill-wrap">
      <button type="button" className="vs-pill" onClick={() => onContinue(app)} title={reference(app.application_id)}
              aria-label={`${draft ? "Continue" : "Open"} ${purposeName(app.purpose)} ${reference(app.application_id)}, ${ready} of ${total} documents${draft ? "" : ", submitted"}`}>
        <span className="vs-pill-ic"><Icon name={draft ? "home" : "check"} /></span>
        <b>{purposeName(app.purpose)}</b>
        <span className="vs-dots" aria-hidden="true">{Array.from({ length: total }, (_, k) => <i key={k} className={k < ready ? "on" : ""} />)}</span>
        <small>{draft ? `${ready} of ${total}` : "Sent"}</small>
        <Icon name="chevron" />
      </button>
      {draft && <button type="button" className="vs-pill-x" onClick={onDelete} aria-label={`Delete draft ${purposeName(app.purpose)} ${reference(app.application_id)}`} title="Delete draft"><Icon name="trash" /></button>}
    </li>
  );
}

/** A draft no lender has seen can go completely. Its documents stay in the vault. */
function DeleteDraft({ app, onClose, onDeleted }: { app: ApplicationListItem; onClose: () => void; onDeleted: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const name = `${purposeName(app.purpose)} ${reference(app.application_id)}`;
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function remove() {
    setBusy(true);
    try { await vault.deleteApplication(app.application_id); toast(`${name} deleted. Your documents are still in your vault.`, "ok"); onClose(); onDeleted(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not delete this application."); setBusy(false); }
  }
  return (
    <dialog ref={dialog} className="vh-dialog vh-small" aria-labelledby="vk-del-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
      <div className="vh-dialog-head">
        <div><p className="eyebrow">Delete draft</p><h2 id="vk-del-title">Delete {name}?</h2></div>
        <button type="button" className="xbtn" onClick={onClose} disabled={busy} aria-label="Close"><Icon name="x" /></button>
      </div>
      <ul className="vh-replace-facts">
        <li>Your answers, progress and chat for this application are deleted. This cannot be undone.</li>
        <li>Your documents stay in your vault, and in any other application they are in.</li>
      </ul>
      <div className="vh-dialog-foot">
        <button type="button" className="btn sec" onClick={onClose} disabled={busy}>Keep it</button>
        <button type="button" className="btn danger" onClick={() => void remove()} disabled={busy}><Icon name="trash" />{busy ? "Deleting…" : "Delete draft"}</button>
      </div>
    </dialog>
  );
}

/* ----------------------------------------------------------------- folders */
interface Kind { value: string; name: string; match: (d: DocumentSummary) => boolean }
function kindsOf(folder: string): Kind[] {
  const loan = LOAN_KINDS.filter(k => k.folder === folder).map(k => ({ value: k.tag, name: k.name, match: (d: DocumentSummary) => d.document_tag === k.tag }));
  const stored = (STORED_KINDS.find(g => g.folder === folder)?.items ?? []).map(item => ({
    value: `label:${item}`, name: item, match: (d: DocumentSummary) => d.document_tag === "other" && d.label === item }));
  return [...loan, ...stored];
}

interface FolderNavProps {
  folders: VaultFolder[]; documents: DocumentSummary[]; selected: string; onSelect: (name: string) => void;
  onOpen: (fileId: string) => void; onAdd: (value: string, folder: string) => void; onAddFolder: () => void; onDeleteFolder: (name: string) => void;
}

/** Folders with their counts. The dark highlight slides to the chosen one; each folder opens into its document types. */
export function FolderNav({ folders, documents, selected, onSelect, onOpen, onAdd, onAddFolder, onDeleteFolder }: FolderNavProps) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const nav = useRef<HTMLElement>(null);
  const thumb = useRef<HTMLSpanElement>(null);
  const count = (name: string) => name ? documents.filter(d => d.folder === name).length : documents.length;
  useLayoutEffect(() => {
    const on = nav.current?.querySelector<HTMLElement>(".vs-frow.on"), t = thumb.current;
    if (!on || !t || !nav.current) return;
    const r = on.getBoundingClientRect(), box = nav.current.getBoundingClientRect();
    t.style.width = `${r.width}px`; t.style.height = `${r.height}px`;
    t.style.transform = `translate(${r.left - box.left - nav.current.clientLeft}px, ${r.top - box.top - nav.current.clientTop}px)`;
  });
  const rows = [{ name: "", default: true, count: documents.length }, ...folders];
  return (
    <nav className="vs-side" aria-label="Folders" ref={nav}>
      <span className="vs-thumb" ref={thumb} aria-hidden="true" />
      <h2>Folders</h2>
      <ul className="vs-fl">
        {rows.map(f => {
          const on = selected === f.name, kinds = f.name ? kindsOf(f.name) : [], expanded = !!open[f.name];
          return (
            <li key={f.name || "all"}>
              <div className={`vs-frow ${on ? "on" : ""}`}>
                <button type="button" className="vs-fbtn" onClick={() => onSelect(f.name)} aria-current={on ? "true" : undefined}>
                  <span className={`vs-fi t-${f.name ? tone(f.name) : "all"}`}><Icon name={f.name ? FOLDER_ICON[f.name] ?? "folder" : "layers"} /></span>
                  <span className="vs-fn">{f.name || "All documents"}</span><em>{count(f.name)}</em>
                </button>
                {kinds.length > 0 && <button type="button" className="vs-exp" aria-expanded={expanded} aria-label={`Document types in ${f.name}`}
                                             onClick={() => setOpen(o => ({ ...o, [f.name]: !o[f.name] }))}><Icon name="chevron" /></button>}
                {f.name && !f.default && <button type="button" className="vs-exp" aria-label={`Delete folder ${f.name}`} title="Delete folder" onClick={() => onDeleteFolder(f.name)}><Icon name="trash" /></button>}
              </div>
              {expanded && <ul className="vs-types" aria-label={`Document types in ${f.name}`}>
                {kinds.map((k, i) => {
                  const doc = documents.find(k.match);
                  return <li key={k.value} style={{ "--i": i } as React.CSSProperties}>
                    <button type="button" className={doc ? "ok" : "add"} onClick={() => doc ? onOpen(doc.file_id) : onAdd(k.value, f.name)}
                            aria-label={doc ? `Open ${k.name}` : `Add ${k.name}`}><Icon name={doc ? "check" : "plus"} /><span>{k.name}</span></button>
                  </li>;
                })}
              </ul>}
            </li>
          );
        })}
      </ul>
      <button type="button" className="vs-addf" onClick={onAddFolder}><Icon name="folderPlus" />Add folder</button>
    </nav>
  );
}

/* ------------------------------------------------------------- documents */
export type Filter = "all" | Status | "inapp";
export const FILTERS: [Filter, string][] = [["all", "All"], ["ready", "Ready"], ["review", "Needs review"], ["reading", "Reading"], ["inapp", "In an application"]];
export const passes = (d: DocumentSummary, f: Filter) => f === "all" || (f === "inapp" ? applicationsOf(d).length > 0 : statusOf(d) === f);

interface RowProps {
  doc: DocumentSummary; applications: ApplicationListItem[]; open: boolean; onMenu: (id: string | null) => void;
  onOpen: (id: string) => void; onChanged: () => void; onMove: (d: DocumentSummary) => void; onReplace: (d: DocumentSummary) => void;
  onVersions: (d: DocumentSummary) => void; onRetype: (d: DocumentSummary) => void; notice: React.ReactNode;
}

/** One document: its folder's icon, name, where it is, the applications it is in, a status pill and one Actions menu. */
export function DocItem(p: RowProps) {
  const { doc, applications, open, onMenu, onOpen } = p;
  const st = statusOf(doc);
  const apps = applicationsOf(doc);
  const name = (id: string) => { const a = applications.find(x => x.application_id === id); return a ? purposeName(a.purpose) : reference(id); };
  return (
    <li className={`vs-doc ${st === "review" ? "review" : ""}`}>
      <span className={`vs-di t-${tone(doc.folder)}`}><Icon name={FOLDER_ICON[doc.folder ?? "Other"] ?? "doc"} /></span>
      <span className="vs-dn">
        <button type="button" className="vs-dname" onClick={() => onOpen(doc.file_id)}>{doc.original_name}</button>
        <small>{doc.label ?? doc.display_name} · {doc.folder ?? "Other"}{doc.uploaded_at ? ` · added ${day(doc.uploaded_at)}` : ""}{(doc.version ?? 1) > 1 ? ` · version ${doc.version}` : ""}</small>
        {apps.length > 0 && <span className="vs-tags">{apps.map(a => <span key={a.application_id} className="vs-tag"><Icon name="home" />In {name(a.application_id)}{a.status !== "draft" ? " (sent)" : ""}</span>)}</span>}
      </span>
      <span className={`vs-status s-${st}`}><i />{STATUS_LABEL[st]}</span>
      <span className="vs-acts">
        <button type="button" className="vs-more" aria-haspopup="menu" aria-expanded={open} onClick={() => onMenu(open ? null : doc.file_id)}>
          <Icon name="more" /><b>Actions</b><span className="sr-only"> for {doc.original_name}</span></button>
        {open && <ActionsMenu {...p} />}
      </span>
      {p.notice}
    </li>
  );
}

function ActionsMenu({ doc, applications, onMenu, onOpen, onChanged, onMove, onReplace, onVersions, onRetype }: RowProps) {
  const menu = useRef<HTMLDivElement>(null);
  const toast = useToast();
  const busy = BUSY.includes(doc.status);
  const locked = applicationsOf(doc).some(a => a.status !== "draft");
  const addable = applications.filter(a => a.status === "draft" && !isIn(doc, a.application_id));
  useEffect(() => {
    menu.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menu.current?.parentElement?.contains(e.target as Node)) onMenu(null);
    };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [onMenu]);
  const act = (fn: () => void) => () => { onMenu(null); fn(); };
  async function attach(a: ApplicationListItem) {
    try { await vault.attach(doc.file_id, a.application_id); toast(`${doc.original_name} added to ${purposeName(a.purpose)}. Your loan team can now see it.`, "ok"); onChanged(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not add this document."); }
  }
  async function remove() {
    const apps = applicationsOf(doc);
    if (!window.confirm(`Permanently delete "${doc.original_name}" from your vault? ${apps.length ? `It will also be removed from ${apps.length === 1 ? "its application" : `all ${apps.length} applications it is in`}, including sent ones. ` : ""}This cannot be undone.`)) return;
    try { await api.deleteDocument(doc.file_id); toast("Document deleted.", "ok"); onChanged(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not delete this document."); }
  }
  return (
    <div className="vs-menu" role="menu" aria-label={`Actions for ${doc.original_name}`} ref={menu}>
      <button role="menuitem" onClick={act(() => onOpen(doc.file_id))}><Icon name="eye" />Open</button>
      {!busy && LOAN_TYPES.includes(doc.document_tag) && addable.map(a => (
        <button key={a.application_id} role="menuitem" onClick={act(() => void attach(a))}><Icon name="home" />Add to {purposeName(a.purpose)}</button>))}
      <button role="menuitem" onClick={act(() => onMove(doc))}><Icon name="folder" />Move to folder</button>
      {doc.document_tag === "other" && !busy && !locked && <button role="menuitem" onClick={act(() => onRetype(doc))}><Icon name="pencil" />Change type</button>}
      <button role="menuitem" disabled={busy} onClick={act(() => onReplace(doc))}><Icon name="refresh" />Replace with new version</button>
      <button role="menuitem" onClick={act(() => onVersions(doc))}><Icon name="history" />Version history</button>
      <hr />
      <button role="menuitem" className="danger" disabled={busy} onClick={act(() => void remove())}><Icon name="trash" />Delete</button>
    </div>
  );
}

/** One line above the list when something needs a look, in the app's greens with a small amber dot. */
export function ReviewStrip({ count, onShow }: { count: number; onShow: () => void }) {
  if (!count) return null;
  return (
    <div className="vs-review">
      <span className="vs-review-ic"><Icon name="alert" /></span>
      <span><b>{count} {count === 1 ? "document needs" : "documents need"} review</b> before {count === 1 ? "it counts" : "they count"} for a loan.</span>
      <button type="button" className="btn" onClick={onShow}>Show {count === 1 ? "it" : "them"}</button>
    </div>
  );
}

/* ------------------------------------------------- ask before attaching */
export interface Ask { fileId: string; applicationId: string }

/** A file added to the vault never joins a loan on its own: when an application still needs it, we ask. */
export function AskAttach({ asks, documents, applications, onDone, onChanged }: {
  asks: Ask[]; documents: DocumentSummary[]; applications: ApplicationListItem[]; onDone: (fileId: string) => void; onChanged: () => void;
}) {
  const toast = useToast();
  const [working, setWorking] = useState("");
  if (!asks.length) return null;
  async function yes(ask: Ask, app: ApplicationListItem, doc: DocumentSummary) {
    setWorking(ask.fileId);
    try { await vault.attach(ask.fileId, ask.applicationId); toast(`${doc.original_name} added to ${purposeName(app.purpose)}. Your loan team can now see it.`, "ok"); onDone(ask.fileId); onChanged(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not add this document."); }
    finally { setWorking(""); }
  }
  return (<>{asks.map(ask => {
    const doc = documents.find(d => d.file_id === ask.fileId), app = applications.find(a => a.application_id === ask.applicationId);
    if (!doc || !app) return null;
    const kind = LOAN_KINDS.find(k => k.tag === doc.document_tag)?.name ?? doc.display_name;
    return (
      <div key={ask.fileId} className="vs-ask" role="group" aria-label={`Add ${doc.original_name} to ${purposeName(app.purpose)}?`}>
        <span className="vs-ask-ic"><Icon name="home" /></span>
        <p><b>{doc.original_name}</b> is a {kind}. Your <b>{purposeName(app.purpose)}</b> still needs one. Add it to the application?
          <small>Once added, your loan team can see this document.</small></p>
        <span className="vs-ask-btns">
          <button type="button" className="btn" disabled={working === ask.fileId} onClick={() => void yes(ask, app, doc)}>Add to {purposeName(app.purpose)}</button>
          <button type="button" className="btn sec" disabled={working === ask.fileId} onClick={() => { onDone(ask.fileId); toast("Kept in your vault only. You can add it later from Actions.", "ok"); }}>Keep in vault only</button>
        </span>
      </div>);
  })}</>);
}

/** Which draft application, if any, still needs this document's type. */
export function needingApp(doc: DocumentSummary, applications: ApplicationListItem[], lists: Record<string, ChecklistRow[]>) {
  if (!LOAN_TYPES.includes(doc.document_tag)) return null;
  return applications.find(a => a.status === "draft" && !isIn(doc, a.application_id)
    && (lists[a.application_id] ?? []).some(r => r.document_tag === doc.document_tag && r.have + r.reading < r.need)) ?? null;
}
