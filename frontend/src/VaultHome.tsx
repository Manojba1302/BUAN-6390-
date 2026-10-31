/** The vault: the first screen after sign-in. Personal storage first, applications when needed.
 *  Top to bottom: a dark welcome block (greeting, New application, your applications), then folders on
 *  the left and the chosen folder's documents in the centre, under a dark header with Upload documents,
 *  search and List / Cards. Uploads are read and filed on their own; they join a loan only when you say so. */
import { useEffect, useRef, useState } from "react";

import { ApiError } from "./api";
import { bytes } from "./format";
import { FOLDER_ICON, Icon } from "./icons";
import { useToast } from "./ui";
import { applicationsOf } from "./Documents";
import { AskAttach, BUSY, DocItem, FILTERS, FolderNav, needingApp, passes, ReviewStrip, statusOf, Welcome, type Ask, type Filter } from "./VaultChecklist";
import { kindOf, kindWithName, LOAN_KINDS, LOAN_TYPES, reference, STORED_KINDS, vault, type ChecklistRow, type DocumentVersion } from "./vault";
import type { ApplicationListItem, DocumentSummary, VaultFolder } from "./types";

export { reference };
const day = (iso?: string | null) => iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";

interface Props {
  firstName?: string;
  documents: DocumentSummary[];
  applications: ApplicationListItem[];
  creating: boolean;
  onOpen: (fileId: string) => void;
  onChanged: () => void;
  onCreateApplication: () => void;
  onContinue: (app: ApplicationListItem) => void;
}

type Dialog = { kind: "retype" | "replace" | "versions" | "move"; doc: DocumentSummary } | { kind: "upload"; value: string; folder: string } | null;

export function VaultHome(props: Props) {
  const { documents, applications, onOpen, onChanged } = props;
  const [folders, setFolders] = useState<VaultFolder[]>([]);
  const [folder, setFolder] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"list" | "cards">("list");
  const [menu, setMenu] = useState<string | null>(null);
  const [lists, setLists] = useState<Record<string, ChecklistRow[]>>({});
  const [dialog, setDialog] = useState<Dialog>(null);
  const [addingFolder, setAddingFolder] = useState(false);
  const toast = useToast();

  const reloadFolders = () => vault.folders().then(setFolders).catch(e => toast(e instanceof ApiError ? e.message : "Could not load your folders."));
  useEffect(() => { void reloadFolders(); }, [documents.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useLoanLists(applications, documents, setLists);
  const { asks, setAsks, upload, track, over, dropProps, fileInput } = useUploads(documents, applications, lists, onChanged);

  const needle = search.trim().toLowerCase();
  const here = documents.filter(d => (!folder || d.folder === folder)
    && (!needle || `${d.original_name} ${d.label ?? ""} ${d.display_name} ${d.folder ?? ""}`.toLowerCase().includes(needle)));
  const shown = here.filter(d => passes(d, filter));
  async function deleteFolder(name: string) {
    if (!window.confirm(`Delete the folder "${name}"? Its documents are kept and move back to their usual folder.`)) return;
    try { await vault.deleteFolder(name); toast(`Folder "${name}" deleted. Its documents were kept.`, "ok"); if (folder === name) setFolder(""); void reloadFolders(); onChanged(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not delete the folder."); }
  }
  const pick = (name: string) => { setFolder(name); setFilter("all"); setMenu(null); };
  const notice = (d: DocumentSummary) => statusOf(d) !== "review" ? null
    : d.status === "failed" ? <p className="vs-note">We could not read this file. Open it to try again, or replace it with a clearer copy.</p>
    : <div className="vs-note"><DocNotice doc={d} canRetype={d.document_tag === "other" && !applicationsOf(d).some(a => a.status !== "draft")} onChanged={onChanged} /></div>;

  return (
    <div className="vh vs">
      <Welcome firstName={props.firstName} applications={applications} lists={lists} creating={props.creating}
               onCreate={props.onCreateApplication} onContinue={props.onContinue} onDeleted={onChanged} />
      <div className="vs-work">
        <FolderNav folders={folders} documents={documents} selected={folder} onSelect={pick} onOpen={onOpen}
                   onAdd={(value, f) => setDialog({ kind: "upload", value, folder: f })} onAddFolder={() => setAddingFolder(true)} onDeleteFolder={name => void deleteFolder(name)} />
        <section className={`vs-main ${over ? "over" : ""}`} aria-labelledby="vs-list-title" {...dropProps}>
          <div className="vs-fpick"><label htmlFor="vs-fsel">Folder</label>
            <select id="vs-fsel" className="ctl" value={folder} onChange={e => pick(e.target.value)}>
              <option value="">All documents ({documents.length})</option>
              {folders.map(f => <option key={f.name} value={f.name}>{f.name} ({documents.filter(d => d.folder === f.name).length})</option>)}
            </select></div>
          <div className="vs-head">
            <h2 id="vs-list-title">{folder || "All documents"}</h2>
            <button type="button" className="vs-up" onClick={() => setDialog({ kind: "upload", value: "other", folder })}><Icon name="upload" />Upload documents</button>
            <label className="vs-search"><Icon name="search" /><span className="sr-only">Search your documents</span>
              <input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search your documents" /></label>
            <div className="vs-views" role="group" aria-label="Layout">
              {(["list", "cards"] as const).map(v => <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>{v === "list" ? "List" : "Cards"}</button>)}
            </div>
          </div>
          {addingFolder && <AddFolder onDone={() => setAddingFolder(false)} onAdded={() => { void reloadFolders(); onChanged(); }} />}
          {filter !== "review" && <ReviewStrip count={here.filter(d => statusOf(d) === "review").length} onShow={() => setFilter("review")} />}
          <AskAttach asks={asks} documents={documents} applications={applications} onChanged={onChanged}
                     onDone={id => setAsks(a => a.filter(x => x.fileId !== id))} />
          <div className="vs-filters" role="group" aria-label="Show">
            {FILTERS.map(([f, label]) => <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f !== "all" && <i className={`d-${f}`} />}{label} <span>{here.filter(d => passes(d, f)).length}</span></button>)}
          </div>
          {shown.length === 0 ? <EmptyFolder searching={!!needle || filter !== "all"} folder={folder} onAdd={() => setDialog({ kind: "upload", value: "other", folder })} />
            : <ul className={`vs-docs ${view}`} aria-label="Documents">{shown.map(d => (
              <DocItem key={d.file_id} doc={d} applications={applications} open={menu === d.file_id} onMenu={setMenu} onOpen={onOpen} onChanged={onChanged}
                       onMove={doc => setDialog({ kind: "move", doc })} onReplace={doc => setDialog({ kind: "replace", doc })}
                       onVersions={doc => setDialog({ kind: "versions", doc })} onRetype={doc => setDialog({ kind: "retype", doc })} notice={notice(d)} />))}</ul>}
        </section>
      </div>
      <input ref={fileInput} type="file" className="sr-only" multiple accept=".pdf,image/*" aria-label="Upload documents"
             onChange={e => { void upload(e.target.files); e.target.value = ""; }} />
      {dialog?.kind === "upload" && <VaultUpload folders={folders} folder={dialog.folder} initial={dialog.value} onClose={() => setDialog(null)} onSaved={ids => { track(ids); onChanged(); }} />}
      {dialog?.kind === "retype" && <RetypeDialog doc={dialog.doc} onClose={() => setDialog(null)} onDone={onChanged} />}
      {dialog?.kind === "replace" && <ReplaceDialog doc={dialog.doc} onClose={() => setDialog(null)} onDone={onChanged} />}
      {dialog?.kind === "versions" && <VersionsDialog doc={dialog.doc} onOpen={onOpen} onClose={() => setDialog(null)} />}
      {dialog?.kind === "move" && <MoveDialog doc={dialog.doc} folders={folders} onClose={() => setDialog(null)} onDone={onChanged} />}
    </div>
  );
}

/** Every application's checklist, loaded again whenever a document changes (the app polls while files are read). */
function useLoanLists(applications: ApplicationListItem[], documents: DocumentSummary[], setLists: (l: Record<string, ChecklistRow[]>) => void) {
  const key = documents.map(d => `${d.file_id}:${d.status}:${d.document_tag}:${(d.applications ?? []).length}`).join("|")
    + applications.map(a => `${a.application_id}:${a.status}`).join("|");
  useEffect(() => {
    let live = true;
    Promise.all(applications.map(a => vault.checklist(a.application_id).then(rows => [a.application_id, rows] as const).catch(() => null)))
      .then(pairs => { if (live) setLists(Object.fromEntries(pairs.filter(Boolean) as [string, ChecklistRow[]][])); });
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** Upload documents: no type is chosen. HomeFlow reads each file and files it; once read, if a draft
 *  application still needs that type, we ask before adding it. Files can also be dropped on the list. */
function useUploads(documents: DocumentSummary[], applications: ApplicationListItem[], lists: Record<string, ChecklistRow[]>, onChanged: () => void) {
  const [pending, setPending] = useState<string[]>([]);
  const [asks, setAsks] = useState<Ask[]>([]);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const toast = useToast();
  useEffect(() => {
    const done = pending.filter(id => { const d = documents.find(x => x.file_id === id); return d && !BUSY.includes(d.status); });
    if (!done.length) return;
    const found = done.flatMap(id => {
      const doc = documents.find(x => x.file_id === id)!, app = needingApp(doc, applications, lists);
      return app ? [{ fileId: id, applicationId: app.application_id }] : [];
    });
    setAsks(a => [...a.filter(x => !found.some(n => n.fileId === x.fileId)), ...found]);
    setPending(p => p.filter(id => !done.includes(id)));
  }, [documents, lists, pending, applications]);
  async function upload(files: FileList | File[] | null) {
    const list = Array.from(files ?? []);
    if (!list.length) return;
    toast(list.length === 1 ? `Uploading ${list[0].name}. We read it and file it for you.` : `Uploading ${list.length} files. We read them and file them for you.`, "ok");
    for (const file of list) {
      try {
        const res = await vault.upload(file, "other", "", null, { auto: true });
        if (res.duplicate_of) toast(`${file.name} is already in your vault, so no second copy was saved.`);
        setPending(p => [...p, res.duplicate_of ?? res.file_id]);
      } catch (e) { toast(e instanceof ApiError ? e.message : `${file.name} did not upload.`); }
    }
    onChanged();
  }
  const dropProps = {
    onDragOver: (e: React.DragEvent) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } },
    onDragLeave: (e: React.DragEvent) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false); },
    onDrop: (e: React.DragEvent) => { if (!e.dataTransfer.files.length) return; e.preventDefault(); setOver(false); void upload(e.dataTransfer.files); },
  };
  /** Files saved from the upload dialog get the same question once they are read. */
  const track = (ids: string[]) => setPending(p => [...p, ...ids]);
  return { asks, setAsks, upload, track, over, dropProps, fileInput };
}

/* ------------------------------------------------------------- add folder */
function AddFolder({ onAdded, onDone }: { onAdded: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [working, setWorking] = useState(false);
  const toast = useToast();
  async function add() {
    if (!name.trim()) return;
    setWorking(true);
    try { const made = await vault.createFolder(name); onAdded(); onDone(); toast(`Folder "${made.name}" added`, "ok"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not add the folder."); setWorking(false); }
  }
  return (
    <form className="vs-new-folder" onSubmit={e => { e.preventDefault(); void add(); }}>
      <label htmlFor="vs-new-folder">New folder</label>
      <input id="vs-new-folder" className="ctl" autoFocus maxLength={40} value={name} placeholder="Folder name" onChange={e => setName(e.target.value)}
             onKeyDown={e => { if (e.key === "Escape") onDone(); }} />
      <button className="btn" disabled={working || !name.trim()}>Add</button>
      <button type="button" className="btn sec" onClick={onDone}>Cancel</button>
    </form>
  );
}

/** Move a document to another folder. */
function MoveDialog({ doc, folders, onClose, onDone }: { doc: DocumentSummary; folders: VaultFolder[]; onClose: () => void; onDone: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [target, setTarget] = useState(doc.folder ?? "Other");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function save() {
    setBusy(true);
    try { await vault.moveDocument(doc.file_id, target); toast(`Moved to ${target}`, "ok"); onDone(); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not move this document."); setBusy(false); }
  }
  return (
    <dialog ref={dialog} className="vh-dialog vh-small" aria-labelledby={`mv-${doc.file_id}`} onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
      <div className="vh-dialog-head">
        <div><p className="eyebrow">Move to folder</p><h2 id={`mv-${doc.file_id}`}>{doc.original_name}</h2></div>
        <button type="button" className="xbtn" onClick={onClose} disabled={busy} aria-label="Close"><Icon name="x" /></button>
      </div>
      <label className="f" htmlFor={`mvs-${doc.file_id}`}><span className="cap">Folder</span>
        <select id={`mvs-${doc.file_id}`} className="ctl" value={target} onChange={e => setTarget(e.target.value)} disabled={busy}>
          {folders.map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
        </select></label>
      <div className="vh-dialog-foot">
        <button type="button" className="btn sec" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="btn" onClick={() => void save()} disabled={busy || target === doc.folder}>{busy ? "Moving…" : "Move"}</button>
      </div>
    </dialog>
  );
}

/** Replace with a new version. The earlier one is kept, and every application that used it moves to the new one. */
function ReplaceDialog({ doc, onClose, onDone }: { doc: DocumentSummary; onClose: () => void; onDone: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const apps = applicationsOf(doc);
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function save() {
    if (!file) return;
    setBusy(true);
    try { const next = await vault.replace(doc.file_id, file); toast(`Saved as version ${next.version ?? 2}. We are reading it now.`, "ok"); onDone(); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not replace this document."); setBusy(false); }
  }
  return (
    <dialog ref={dialog} className="vh-dialog vh-small" aria-labelledby={`rp-${doc.file_id}`} onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
      <div className="vh-dialog-head">
        <div><p className="eyebrow">Replace file</p><h2 id={`rp-${doc.file_id}`}>{doc.original_name}</h2></div>
        <button type="button" className="xbtn" onClick={onClose} disabled={busy} aria-label="Close"><Icon name="x" /></button>
      </div>
      <button type="button" className="btn sec" onClick={() => input.current?.click()} disabled={busy}><Icon name="file" />{file ? "Choose a different file" : "Choose the new file"}</button>
      <input ref={input} type="file" className="sr-only" accept=".pdf,image/*" onChange={e => { setFile(e.target.files?.[0] ?? null); e.target.value = ""; }} />
      {file && <p className="vh-replace-pick"><Icon name="doc" /><b>{file.name}</b><small>{bytes(file.size)} · becomes version {(doc.version ?? 1) + 1}</small></p>}
      <ul className="vh-replace-facts">
        <li>Version {doc.version ?? 1} is kept under its versions, and you can still open it.</li>
        <li>We read the new file again. Values you confirmed yourself in an application are kept.</li>
        {apps.length > 0 && <li>{apps.map(a => reference(a.application_id)).join(", ")} will use the new version from now on{apps.some(a => a.status !== "draft") ? ", including the submitted application" : ""}.</li>}
      </ul>
      <div className="vh-dialog-foot">
        <button type="button" className="btn sec" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="btn" onClick={() => void save()} disabled={busy || !file}><Icon name="refresh" />{busy ? "Replacing…" : "Replace file"}</button>
      </div>
    </dialog>
  );
}

/** Every version of a document, newest first. Earlier versions stay viewable by the customer. */
function VersionsDialog({ doc, onOpen, onClose }: { doc: DocumentSummary; onOpen: (id: string) => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [list, setList] = useState<DocumentVersion[] | null>(null);
  const toast = useToast();
  useEffect(() => {
    dialog.current?.showModal();
    vault.versions(doc.file_id).then(v => setList([...v].reverse())).catch(e => toast(e instanceof ApiError ? e.message : "Could not load the versions."));
  }, [doc.file_id]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <dialog ref={dialog} className="vh-dialog vh-small" aria-labelledby={`vs-${doc.file_id}`} onCancel={e => { e.preventDefault(); onClose(); }}>
      <div className="vh-dialog-head">
        <div><p className="eyebrow">Versions</p><h2 id={`vs-${doc.file_id}`}>{doc.label ?? doc.display_name}</h2></div>
        <button type="button" className="xbtn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
      </div>
      {!list ? <p className="hint">Loading…</p> : <ul className="vh-versions">{list.map(v => (
        <li key={v.file_id}>
          <span><b>Version {v.version}{v.current ? " · current" : ""}</b><small>{v.original_name} · {bytes(v.size_bytes)} · {day(v.uploaded_at)}</small></span>
          <button type="button" className="btn sec" onClick={() => { onClose(); onOpen(v.file_id); }}><Icon name="eye" />Open</button>
        </li>))}</ul>}
      <p className="hint">Applications only see the current version.</p>
    </dialog>
  );
}

/** What HomeFlow noticed about a stored file: a type it suggests, or more than one document in one file. */
function DocNotice({ doc, canRetype, onChanged }: { doc: DocumentSummary; canRetype: boolean; onChanged: () => void }) {
  const cls = doc.classification;
  const [working, setWorking] = useState(false);
  const toast = useToast();
  if (!cls || doc.status !== "completed") return null;
  const suggested = doc.document_tag === "other" && cls.outcome === "mismatched" && LOAN_TYPES.includes(cls.detected_type) ? cls.detected_type : null;
  async function accept(tag: string) {
    setWorking(true);
    try { await vault.changeType(doc.file_id, tag); toast(`Saved as ${typeName(tag)}`, "ok"); onChanged(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not change the type."); setWorking(false); }
  }
  const moved = doc.document_tag === "other" && cls.outcome === "mismatched" && cls.selected_type !== "other";
  if (!moved && !suggested && !cls.mixed_document) return null;
  return (<div className="vh-notes">
    {moved && !suggested && <span className="vh-note"><Icon name="info" /><span>You chose {typeName(cls.selected_type)}, but this does not look like one, so it was saved as Other.</span></span>}
    {suggested && <span className="vh-note">
      <Icon name="info" />
      <span>{moved ? `You chose ${typeName(cls.selected_type)}, but this looks like a ${typeName(suggested)}, so it was saved as Other.` : `This looks like a ${typeName(suggested)}.`}
        {canRetype && <button type="button" disabled={working} onClick={() => void accept(suggested)}>Make it a {typeName(suggested)}</button>}</span>
    </span>}
    {cls.mixed_document && <span className="vh-note">
      <Icon name="alert" /><span>This file seems to hold more than one document. Saving each one on its own makes it easier to find and use.</span>
    </span>}
  </div>);
}

/** The full list of what a document can be, grouped as the household checklist groups it. */
function TypeSelect({ id, value, onChange, disabled }: { id: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <select id={id} className="ctl" value={value} onChange={e => onChange(e.target.value)} disabled={disabled}>
      <optgroup label="Loan documents · used in applications">
        {LOAN_KINDS.map(k => <option key={k.tag} value={k.tag}>{k.name}</option>)}
      </optgroup>
      {STORED_KINDS.map(g => (
        <optgroup key={g.folder} label={g.folder}>
          {g.items.map(item => <option key={item} value={`label:${item}`}>{item}</option>)}
        </optgroup>
      ))}
      <optgroup label="Not listed"><option value="other">Something else</option></optgroup>
    </select>
  );
}

/** "Something else": the customer may name the type themselves. */
function TypedName({ id, value, onChange, disabled }: { id: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <label className="f" htmlFor={id}><span className="cap">Name this type <small>(optional)</small></span>
      <input id={id} className="ctl" value={value} maxLength={60} disabled={disabled} placeholder="For example: Lease agreement"
             onChange={e => onChange(e.target.value)} /></label>
  );
}

/** A document saved as Other can become any type. One picked from the list stays as it is. */
function RetypeDialog({ doc, onClose, onDone }: { doc: DocumentSummary; onClose: () => void; onDone: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState(doc.label && STORED_KINDS.some(g => g.items.includes(doc.label!)) ? `label:${doc.label}` : "other");
  const [typed, setTyped] = useState(value === "other" ? doc.label ?? "" : "");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function save() {
    const kind = kindWithName(value, typed);
    setBusy(true);
    try { await vault.changeType(doc.file_id, kind.tag, kind.label); toast(`Saved as ${kind.name}`, "ok"); onDone(); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not change the type."); setBusy(false); }
  }
  return (
    <dialog ref={dialog} className="vh-dialog vh-small" aria-labelledby={`rt-${doc.file_id}`} onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
      <div className="vh-dialog-head">
        <div><p className="eyebrow">Change type</p><h2 id={`rt-${doc.file_id}`}>{doc.original_name}</h2></div>
        <button type="button" className="xbtn" onClick={onClose} disabled={busy} aria-label="Close"><Icon name="x" /></button>
      </div>
      <label className="f" htmlFor={`rts-${doc.file_id}`}><span className="cap">What is it?</span></label>
      <TypeSelect id={`rts-${doc.file_id}`} value={value} onChange={setValue} disabled={busy} />
      {value === "other" && <TypedName id={`rtn-${doc.file_id}`} value={typed} onChange={setTyped} disabled={busy} />}
      <p className="hint">{LOAN_TYPES.includes(value) ? "Once it is a loan document, its type is fixed. Its details are read when you add it to an application." : "You can change this again later."}</p>
      <div className="vh-dialog-foot">
        <button type="button" className="btn sec" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="btn" onClick={() => void save()} disabled={busy}>{busy ? "Saving…" : "Save type"}</button>
      </div>
    </dialog>
  );
}

function EmptyFolder({ searching, folder, onAdd }: { searching: boolean; folder: string; onAdd: () => void }) {
  return (
    <div className="vh-empty">
      <span className="vh-empty-ic"><Icon name={searching ? "search" : FOLDER_ICON[folder] ?? "folder"} /></span>
      <b>{searching ? "Nothing matches" : folder ? `${folder} is empty` : "Your vault is empty"}</b>
      <p>{searching ? "Try another name, or show all documents." : "Upload a document and we read it and file it for you. You do not need a loan application to use your vault."}</p>
      {!searching && <button type="button" className="btn" onClick={onAdd}><Icon name="upload" />Upload documents</button>}
    </div>
  );
}

/* ---------------------------------------------------------------- upload */
type Pick = { id: string; file: File; url: string; isPdf: boolean; tag: string; state: "new" | "saving" };
const typeName = (value: string) => kindOf(value).name;

/** Nothing is refused: every file is stored, read and made searchable. If it is not the type chosen,
 *  HomeFlow keeps it as Other and suggests a type on the vault list. */
function VaultUpload({ folders, folder, initial = "other", onClose, onSaved }: {
  folders: VaultFolder[]; folder: string; initial?: string; onClose: () => void; onSaved: (fileIds: string[]) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const [picks, setPicks] = useState<Pick[]>([]);
  const [tag, setTag] = useState(initial);
  const [typed, setTyped] = useState("");
  // Empty until the customer picks a folder; until then the folder follows the type chosen.
  const [target, setTarget] = useState(folder);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const picksRef = useRef(picks);
  useEffect(() => { picksRef.current = picks; }, [picks]);
  useEffect(() => { dialog.current?.showModal(); return () => picksRef.current.forEach(p => URL.revokeObjectURL(p.url)); }, []);

  function add(files: FileList | null) {
    if (!files) return;
    // Read the list now: the input is cleared right after, which empties a live FileList.
    const incoming: Pick[] = Array.from(files).map(file => ({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, file, url: URL.createObjectURL(file),
      isPdf: file.type.includes("pdf") || /\.pdf$/i.test(file.name), tag, state: "new",
    }));
    setPicks(xs => [...xs, ...incoming]);
  }
  function drop(id: string) {
    setPicks(xs => { xs.filter(x => x.id === id).forEach(x => URL.revokeObjectURL(x.url)); return xs.filter(x => x.id !== id); });
  }
  function chooseType(next: string) {
    setTag(next);
    setPicks(xs => xs.map(x => ({ ...x, tag: next })));
  }

  async function save() {
    setBusy(true);
    let saved = 0, left = 0;
    const ids: string[] = [];
    for (const p of picksRef.current) {
      setPicks(xs => xs.map(x => x.id === p.id ? { ...x, state: "saving" } : x));
      const kind = kindWithName(p.tag, typed);
      // Left as Other, with no name and no folder of their own: HomeFlow works out the type and files it.
      const auto = p.tag === "other" && !typed.trim() && (!target || target === kind.folder);
      try {
        const res = await vault.upload(p.file, kind.tag, target || kind.folder, kind.label, { auto });   // unchanged: target wins
        ids.push(res.duplicate_of ?? res.file_id);
        if (res.duplicate_of) toast(`${p.file.name} is already in your vault, so no second copy was saved.`);
        else saved += 1;
        drop(p.id);
      } catch (e) {
        left += 1;
        setPicks(xs => xs.map(x => x.id === p.id ? { ...x, state: "new" } : x));
        toast(e instanceof ApiError ? e.message : `${p.file.name} did not upload.`);
      }
    }
    setBusy(false);
    if (saved) toast(`${saved} document${saved === 1 ? "" : "s"} saved. We are reading ${saved === 1 ? "it" : "them"} now.`, "ok");
    if (ids.length) onSaved(ids);
    if (!left) onClose();
  }

  const kind = kindWithName(tag, typed);
  return (
    <dialog ref={dialog} className="vh-dialog" aria-labelledby="vh-up-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
      <div className="vh-dialog-head">
        <div><p className="eyebrow">Add to your vault</p><h2 id="vh-up-title">Add a document</h2></div>
        <button type="button" className="xbtn" onClick={onClose} disabled={busy} aria-label="Close"><Icon name="x" /></button>
      </div>
      <div className="vh-up-fields">
        <label className="f" htmlFor="vh-up-type"><span className="cap">What is it?</span>
          <TypeSelect id="vh-up-type" value={tag} onChange={chooseType} disabled={busy} /></label>
        <label className="f" htmlFor="vh-up-folder"><span className="cap">Save in folder</span>
          <select id="vh-up-folder" className="ctl" value={target || kind.folder} onChange={e => setTarget(e.target.value)} disabled={busy}
                  aria-describedby="vh-up-folder-hint">
            {folders.map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>
          <small id="vh-up-folder-hint" className="vh-folder-hint">{!target || target === kind.folder
            ? `Suggested for ${tag === "other" && !typed.trim() ? "documents not on the list" : kind.name}`
            : `${kind.name} usually goes in ${kind.folder}`}</small></label>
        {tag === "other" && <TypedName id="vh-up-name" value={typed} onChange={setTyped} disabled={busy} />}
      </div>
      <p className="hint">{LOAN_TYPES.includes(tag)
        ? "We read it and check that it is what you chose. Its details are filled in when you add it to a loan application."
        : !typed.trim() && (!target || target === kind.folder)
          ? "Not sure what it is? Leave it as Other. We read it, and a loan document gets its own type and folder."
          : "Stored safely and searchable by its text. If it turns out to be a loan document, we suggest that type."}</p>
      <div className="drop" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); add(e.dataTransfer.files); }}>
        <span className="di"><Icon name="upload" /></span>
        <b>Drag files here</b>
        <p>PDF, JPG, PNG or HEIC, up to 20 MB each</p>
        <div className="dropbtns">
          <button type="button" className="btn sec" onClick={() => fileInput.current?.click()} disabled={busy}><Icon name="file" />Choose files</button>
          <button type="button" className="btn sec" onClick={() => cameraInput.current?.click()} disabled={busy}><Icon name="camera" />Take a photo</button>
        </div>
      </div>
      <input ref={fileInput} type="file" className="sr-only" multiple accept=".pdf,image/*" onChange={e => { add(e.target.files); e.target.value = ""; }} />
      <input ref={cameraInput} type="file" className="sr-only" accept="image/*" capture="environment" onChange={e => { add(e.target.files); e.target.value = ""; }} />
      {picks.length > 0 && <ul className="vh-picks">{picks.map(p => (
        <li key={p.id}>
          <div className="vh-pick-top">
            <span className="vh-pick-thumb">{p.isPdf ? <Icon name="file" /> : <img src={p.url} alt="" />}</span>
            <span className="vh-pick-name"><b>{p.file.name}</b><small>{bytes(p.file.size)} · {kindWithName(p.tag, typed).name} · {p.state === "saving" ? "saving…" : "preview only until you save"}</small></span>
            <a href={p.url} target="_blank" rel="noreferrer">Preview</a>
            <button type="button" className="xbtn" disabled={busy} onClick={() => drop(p.id)} aria-label={`Remove ${p.file.name}`}><Icon name="x" /></button>
          </div>
        </li>))}</ul>}
      <div className="vh-dialog-foot">
        <button type="button" className="btn sec" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="btn" onClick={() => void save()} disabled={busy || !picks.length}>
          <Icon name="upload" />{busy ? "Saving…" : picks.length ? `Save ${picks.length} file${picks.length === 1 ? "" : "s"}` : "Save"}
        </button>
      </div>
    </dialog>
  );
}
