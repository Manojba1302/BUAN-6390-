/** Local preview first; server classification starts only after Submit. */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { api, ApiError } from "./api";
import { bytes } from "./format";
import { CATEGORY_ICON, Icon } from "./icons";
import { useToast } from "./ui";
import type { ChecklistItem, DocumentSummary, StagedFile } from "./types";
import { kindOf, LOAN_TYPES, vault } from "./vault";

const TYPE_LABELS: Record<string, string> = {
  w2: "W-2", paystub: "Pay stub", bank_statement: "Bank statement", drivers_license: "Driver's license",
  ssn_card: "Social Security card", other: "Other document", unknown: "Not recognised",
};

interface Props {
  applicationId: string;
  checklist: ChecklistItem[];
  documents: DocumentSummary[];
  vaultDocuments: DocumentSummary[];
  onUploaded: () => void;
  onOpenDoc: (fileId: string) => void;
  /** Replaces the plain step heading, e.g. with the dark step header. */
  header?: ReactNode;
}

/** have counts documents that were read (fields pulled out); uploads still being read or not readable do not count yet. */
type CatState = { have: number; need: number; uploaded: number; reading: number; unread: number; flagged: boolean; satisfied: boolean };
const wasRead = (d: DocumentSummary) => d.status === "completed" && d.extracted_field_count > 0;

export const DOCUMENTS_LEDE = "Choose what a file is before you pick it, so we can tell you straight away if something looks wrong. Preview stays on your device until you press Submit. We then check the document type and save accepted files.";

export function DocumentsStep(props: Props) {
  const { applicationId, checklist, documents, onUploaded, onOpenDoc } = props;
  const [activeCat, setActiveCat] = useState<string | null>(null);
  const [staged, setStaged] = useState<StagedFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [stored, setStored] = useState<Record<string,{id:string;status:string;application?:string|null}>>({});
  const [showVault, setShowVault] = useState(false);
  const uploader = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const stagedRef = useRef(staged);
  useEffect(() => { stagedRef.current = staged; }, [staged]);
  useEffect(() => () => { stagedRef.current.forEach(s => s.previewUrl && URL.revokeObjectURL(s.previewUrl)); }, []);

  useEffect(() => {
    if(activeCat && uploader.current && !uploader.current.open) uploader.current.showModal();
  }, [activeCat]);

  const state = (tag: string): CatState => {
    const mine = documents.filter((d) => d.document_tag === tag);
    const need = checklist.find((c) => c.document_tag === tag)?.required_count ?? 1;
    const have = mine.filter(wasRead).length;
    const reading = mine.filter((d) => ["uploaded", "queued", "processing"].includes(d.status)).length;
    const unread = mine.length - have - reading;
    const flagged = unread > 0 || mine.some((d) => d.classification &&
      d.classification.outcome !== "matched" && d.classification.detected_type !== d.document_tag);
    return { have, need, uploaded: mine.length, reading, unread, flagged, satisfied: have > 0 && have >= need };
  };

  const missing = checklist.filter((c) => c.required_count > 0 && !state(c.document_tag).satisfied);

  /** Stage files locally, then ask the server what each one looks like. */
  async function stage(files: FileList | null) {
    if (!files || !activeCat) return;
    const incoming: StagedFile[] = Array.from(files).map((file) => ({
      id: `${Date.now()}-${file.name}-${Math.random().toString(36).slice(2, 7)}`,
      file, cat: activeCat, name: file.name, size: file.size,
      isPdf: file.type.includes("pdf") || /\.pdf$/i.test(file.name),
      previewUrl: URL.createObjectURL(file),
      status: "local", result: null, kept: false,
    }));
    setStaged((xs) => [...xs, ...incoming]);

  }

  const ready = staged.filter(s => !stored[s.id]).filter(s => s.status === "local" || s.status === "error" || s.result?.outcome === "failed" || (s.status === "done" && (s.result?.outcome === "matched" || s.kept)));

  async function upload() {
    if (!ready.length || busy) return;
    setBusy(true);
    let done = 0;
    for (const item of ready) {
      try {
        let result = item.result;
        if (!item.kept && (!result || result.outcome === "failed")) {
          setStaged(xs => xs.map(x => x.id === item.id ? {...x,status:"checking"} : x));
          result = await api.classify(item.file,item.cat);
          setStaged(xs => xs.map(x => x.id === item.id ? {...x,status:"done",result} : x));
        }
        if (!item.kept && result?.outcome !== "matched") continue;
        const res = await api.upload(item.file,item.cat,applicationId,item.kept);
        if (res.duplicate_of && res.application_id === applicationId) {
          if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
          setStaged(xs => xs.filter(x => x.id !== item.id));
          done += 1;
          continue;
        }
        if (res.duplicate_of) {
          setStored(xs => ({...xs,[item.id]:{id:res.file_id,status:res.status,application:res.application_id}}));
          toast("This file is already saved. Review its stored copy below.");onUploaded();continue;
        }
        if (res.message) {toast(res.message);continue;}
        if(item.previewUrl) URL.revokeObjectURL(item.previewUrl);
        setStaged(xs => xs.filter(x => x.id !== item.id));
        done += 1;
      } catch(err) {
        setStaged(xs => xs.map(x => x.id === item.id ? {...x,status:"error"} : x));
        toast(err instanceof ApiError ? err.message : `${item.name} did not upload.`);
      }
    }
    setBusy(false);
    if(done){toast(`${done} file${done>1?"s":""} added to this application`,"ok");onUploaded();if(done === staged.length) setActiveCat(null);}
  }

  function discard() {
    staged.forEach((s) => s.previewUrl && URL.revokeObjectURL(s.previewUrl));
    setStaged([]);setStored({});
  }

  return (
    <>
      {props.header ?? <>
        <p className="eyebrow">Step 2</p>
        <h1 className="h1">Your documents</h1>
        <p className="lede">{DOCUMENTS_LEDE}</p>
      </>}
      <ol className="upload-guide" aria-label="Upload steps">
        <li><span>1</span>Choose document type</li>
        <li><span>2</span>Preview your file</li>
        <li><span>3</span>Upload and review</li>
      </ol>


      <section className="card need-card">
        {(() => {
          const requiredTypes = checklist.filter((c) => c.required_count > 0).length;
          const doneTypes = requiredTypes - missing.length;
          const pct = requiredTypes ? Math.round((doneTypes / requiredTypes) * 100) : 100;
          return (
            <div className={`need-head ${missing.length ? "" : "done"}`}>
              <div className="need-copy">
                <h2>What we need</h2>
                <p role="status">{missing.length
                  ? <><b>{missing.length} to go</b> before we can review your application.</>
                  : <><b>Every requested document is here.</b> Review the dates and pages too. File counts alone do not verify statement periods or completeness.</>}</p>
              </div>
              <span className="need-ring" style={{ "--v": pct } as CSSProperties} role="img"
                    aria-label={`${doneTypes} of ${requiredTypes} required document types complete`}>
                <span>{missing.length ? <>{doneTypes}<small>/{requiredTypes}</small></> : <Icon name="check" />}</span>
              </span>
            </div>
          );
        })()}
        <p className="document-period-note">For the supplied W-2 purchase workflow: two latest paystubs, two years of W-2s and two months of statements for each bank account. Your loan team may request updates.</p>
        <p className="hint">
          PDF, JPG, PNG or HEIC. Up to 20 MB each. A photo from your phone is fine if every
          corner is in frame.
        </p>
        <div className="doclist">
          {checklist.map((c) => {
            const s = state(c.document_tag);
            const cls = s.flagged ? "warn" : s.satisfied ? "ok" : "";
            const fill = s.uploaded ? "has" : s.need ? "needed" : "optional";
            const extra = [s.reading ? `${s.reading} being read` : "", s.unread ? `${s.unread} could not be read` : ""].filter(Boolean).join(" · ");
            return (
              <button key={c.document_tag} className={`doctile ${cls} ${fill} doctype-${c.document_tag}`}
                      onClick={() => { setActiveCat(c.document_tag); discard(); }}>
                <span className="tile-art" aria-hidden="true">{s.uploaded ? <TileArt tag={c.document_tag} /> : <Icon name="plus" />}</span>
                <span className="ti"><Icon name={CATEGORY_ICON[c.document_tag] ?? "doc"} /></span>
                <span className="tt">
                  <b>{c.display_name}</b>
                  <small className="document-guidance">{c.guidance}</small><span>{s.uploaded ? (s.need ? `${s.have} of ${s.need} read` : `${s.have} read`) : (s.need ? `0 of ${s.need} uploaded` : "No files uploaded")}{extra ? ` · ${extra}` : ""}</span>
                </span>
                {s.flagged ? <span className="chip w"><Icon name="alert" />Needs a look</span>
                  : s.satisfied ? <span className="chip g"><Icon name="check" />Read</span>
                  : s.reading ? <span className="chip n">Reading…</span>
                  : s.uploaded ? <span className="chip a">{s.have} of {s.need}</span>
                  : <span className="chip n">{s.need ? "Required" : "Optional"}</span>}
                <span className="go"><Icon name="chevron" /></span>
              </button>
            );
          })}
        </div>
      </section>

      {activeCat && (
        <dialog className="document-upload-dialog" ref={uploader} aria-labelledby="uploader-title" onCancel={e => { if(busy){e.preventDefault();return;} setActiveCat(null);discard(); }}>
        <section className="card">
          <div className="rep-head">
            <b id="uploader-title">Upload {checklist.find((c) => c.document_tag === activeCat)?.display_name}</b>
            <button className="xbtn" onClick={() => { setActiveCat(null); discard(); }}
                    disabled={busy} aria-label="Close uploader"><Icon name="x" /></button>
          </div>
          <p className="hint">{checklist.find((c) => c.document_tag === activeCat)?.guidance}</p>

          <div className="drop" onDragOver={(e) => e.preventDefault()}
               onDrop={(e) => { e.preventDefault(); void stage(e.dataTransfer.files); }}>
            <span className="di"><Icon name="upload" /></span>
            <b>Drag a file here</b>
            <p>or choose one from your device</p>
            <div className="dropbtns">
              <button className="btn sec" onClick={() => fileInput.current?.click()}>
                <Icon name="file" />Choose a file
              </button>
              <button className="btn sec" onClick={() => cameraInput.current?.click()}>
                <Icon name="camera" />Take a photo
              </button>
            </div>
          </div>

          <VaultPicker documents={props.vaultDocuments} tag={activeCat} applicationId={applicationId} compact
                       onOpen={id => { setActiveCat(null); discard(); onOpenDoc(id); }}
                       onAttached={() => { onUploaded(); setActiveCat(null); discard(); }} />

          <input ref={fileInput} type="file" className="sr-only" multiple
                 accept=".pdf,image/*" onChange={(e) => { void stage(e.target.files); e.target.value = ""; }} />
          <input ref={cameraInput} type="file" className="sr-only"
                 accept="image/*" capture="environment"
                 onChange={(e) => { void stage(e.target.files); e.target.value = ""; }} />

          {staged.length > 0 && (
            <div className="stage">
              {staged.map((item) => (
                <StagedRow key={item.id} item={item}
                           checklist={checklist} onCategory={(cat) => setStaged(xs => xs.map(x => x.id === item.id ? {...x,cat,result:null,kept:false,status:"local"} : x))}
                           onKeep={() => setStaged((xs) => xs.map((x) =>
                             x.id === item.id ? { ...x, kept: true } : x))}
                           onRemove={() => {
                             if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
                             setStaged((xs) => xs.filter((x) => x.id !== item.id));
                           }} />
              ))}
            </div>
          )}

          {Object.entries(stored).map(([id,copy]) => <div className="banner" role="status" key={id}><Icon name="info"/><div><b>Already saved - no new upload needed</b><p>{copy.application && copy.application !== applicationId ? "This file is linked to another application; it has not been moved." : copy.application ? "This file is already attached to this application." : "This file is in My Vault. Choose it from My Vault to attach it here."} {copy.status === "failed" ? "Reading failed. Open it and choose Retry reading." : ["queued","processing"].includes(copy.status) ? "Reading is still in progress." : "Its extracted details are available to review."}</p><button type="button" className="btn sec" onClick={() => {setActiveCat(null);discard();onOpenDoc(copy.id);}}>Review stored file</button></div></div>)}
          {staged.length > 0 && (
            <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap", alignItems: "center" }}>
              <button className="btn" onClick={() => void upload()} disabled={!ready.length || busy}>
                <Icon name="upload" />
                {busy ? "Checking and saving…" : `Submit ${ready.length} file${ready.length === 1 ? "" : "s"}`}
              </button>
              <button className="btn sec" disabled={busy} onClick={discard}>Discard</button>
              {staged.filter(s=>!stored[s.id]).length > ready.length && (
                <span className="footnote">
                  {staged.filter(s=>!stored[s.id]).length - ready.length} file{staged.length - ready.length > 1 ? "s" : ""}{" "}
                  {staged.some((s) => s.status === "checking") ? "being checked" : "need your confirmation"}
                </span>
              )}
            </div>
          )}
        </section>
        </dialog>
      )}

      <section className="card">
        <h2>Use a document from My Vault</h2>
        <p className="hint">Attach a file you already keep in your vault. No second copy is uploaded.</p>
        <button className="btn sec" onClick={() => setShowVault(!showVault)}><Icon name="folder" />{showVault ? "Hide vault documents" : "Choose from My Vault"}</button>
        {showVault && <VaultPicker documents={props.vaultDocuments} applicationId={applicationId} onOpen={onOpenDoc} onAttached={onUploaded} />}
      </section>

      {documents.length > 0 && (
        <section className="card">
          <h2>Uploaded</h2>
          <p className="hint">
            Open any document to see what we read from it and correct anything we got wrong.
          </p>
          <div className="vaultgrid">
            {documents.map((d) => <DocCard key={d.file_id} doc={d} onOpen={onOpenDoc} mode="application" applicationId={applicationId} onChanged={onUploaded} />)}
          </div>
        </section>
      )}
    </>
  );
}

/** The applications a document is in (older API answers only carry the latest one). */
export function applicationsOf(doc: DocumentSummary) {
  return doc.applications ?? (doc.application_id ? [{ application_id: doc.application_id, status: doc.application_status ?? "draft" }] : []);
}
export const isIn = (doc: DocumentSummary, applicationId?: string) => !!applicationId && applicationsOf(doc).some(a => a.application_id === applicationId);

/** Vault files not yet in this application, ready to attach (they may be in another one too). With a tag, files of that type come first. */
function VaultPicker({ documents, tag, applicationId, compact, onOpen, onAttached }: {
  documents: DocumentSummary[]; tag?: string; applicationId: string; compact?: boolean;
  onOpen: (id: string) => void; onAttached: () => void;
}) {
  const [all, setAll] = useState(!tag);
  const [working, setWorking] = useState<string | null>(null);
  const toast = useToast();
  const free = documents.filter(d => !isIn(d, applicationId));
  const shown = all ? free : free.filter(d => d.document_tag === tag);
  if (compact && !free.length) return null;
  async function attach(doc: DocumentSummary) {
    setWorking(doc.file_id);
    try { await api.linkDocument(doc.file_id, applicationId); toast(`${doc.original_name} attached from your vault`, "ok"); onAttached(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not attach this document."); }
    finally { setWorking(null); }
  }
  return (
    <div className={`vault-pick ${compact ? "compact" : ""}`}>
      {compact && <p className="vault-pick-or"><span>or attach from your vault</span></p>}
      {shown.length ? <ul>{shown.map(d => (
        <li key={d.file_id}>
          <span className="vp-ic"><Icon name={CATEGORY_ICON[d.document_tag] ?? "doc"} /></span>
          <button type="button" className="vp-name" onClick={() => onOpen(d.file_id)}><b>{d.original_name}</b><small>{d.label ?? d.display_name} · {d.folder ?? "Vault"}</small></button>
          <button type="button" className="btn sec" disabled={!!working} onClick={() => void attach(d)}><Icon name="plus" />{working === d.file_id ? "Attaching…" : "Attach"}</button>
        </li>))}</ul>
        : <p className="hint">{free.length ? "No vault files of this type yet." : "Every file in your vault is already in this application. Files you add from the vault page appear here."}</p>}
      {tag && free.length > shown.length && <button type="button" className="linkbtn" onClick={() => setAll(true)}>Show all {free.length} vault files</button>}
      <p className="footnote">A file can be in more than one application. Attaching it here does not remove it from another one.</p>
    </div>
  );
}

function StagedRow({ item, onKeep, onRemove, checklist, onCategory }: {
  checklist: ChecklistItem[]; onCategory: (cat:string)=>void;
  item: StagedFile; onKeep: () => void; onRemove: () => void;
}) {
  const r = item.result;
  return (
    <div className="sitem">
      {item.previewUrl && <div className="local-document-preview">{item.isPdf ? <object data={item.previewUrl} type="application/pdf" aria-label={`Preview of ${item.name}`}><p>PDF preview is unavailable in this browser. <a href={item.previewUrl} target="_blank" rel="noreferrer">Open selected PDF</a></p></object> : <img src={item.previewUrl} alt={`Preview of ${item.name}`} />}<a href={item.previewUrl} target="_blank" rel="noreferrer">Open full preview</a></div>}
      <div className="sitem-top">
        <span className="thumb">
          {item.previewUrl && !item.isPdf
            ? <img src={item.previewUrl} alt="" />
            : <Icon name={item.isPdf ? "file" : "image"} />}
        </span>
        <span className="meta">
          <b>{item.name}</b><label className="f">Selected document type<select className="ctl" value={item.cat} disabled={item.status==="checking"} onChange={e=>onCategory(e.target.value)}>{checklist.map(c=><option key={c.document_tag} value={c.document_tag}>{c.display_name}</option>)}</select></label>{r && <p className="hint">Detected type: {r.detected_type === "unknown" ? "not recognised" : checklist.find(c=>c.document_tag===r.detected_type)?.display_name ?? r.detected_type}. Selected type: {checklist.find(c=>c.document_tag===item.cat)?.display_name ?? item.cat}. Changing the type checks it again on Submit.</p>}
          <span className="sub">{bytes(item.size)} &middot; {item.isPdf ? "PDF" : "Image"} &middot; awaiting upload</span>

          {item.status === "local" && <p className="hint">Preview only · not sent to the server. AI detection starts after Submit.</p>}
          {item.status === "checking" && (
            <div className="scanning"><span className="spin" /> Checking what this document is</div>
          )}

          {item.status === "error" && (
            <div className="res"><span className="chip r"><Icon name="alert" />We could not check this file</span></div>
          )}

          {r && (
            <>
              <div className="res">
                <span className={`chip ${r.outcome === "matched" ? "g" : r.outcome === "failed" || r.outcome === "unreadable" ? "r" : "w"}`}>
                  <Icon name={r.outcome === "matched" ? "check" : "alert"} />{r.message}
                </span>
                {item.kept && <span className="chip a">You confirmed this</span>}
              </div>
              {r.evidence.length > 0 && (
                <div className="evid">
                  We found <code>{r.evidence[0]}</code>{r.evidence[1] ? <> and <code>{r.evidence[1]}</code></> : null} on page 1.
                </div>
              )}
              {r.outcome === "unreadable" && (
                <div className="evid">
                  Retake the photo on a flat surface, with no glare, and all four corners inside the frame.
                </div>
              )}
              {r.outcome === "mismatched" && !item.kept && (
                <p className="hint">If you upload it anyway, it is saved in your vault as Other and does not count as {checklist.find(c => c.document_tag === item.cat)?.display_name ?? "this type"}. You can change its type later.</p>
              )}
              {(r.outcome === "mismatched" || r.outcome === "unknown" || r.outcome === "failed") && !item.kept && (
                <div className="sitem-act">
                  {r.outcome === "mismatched" && checklist.some(c => c.document_tag === r.detected_type) &&
                    <button className="btn" onClick={() => onCategory(r.detected_type)}>Use {checklist.find(c => c.document_tag === r.detected_type)?.display_name} instead</button>}
                  <button className="btn sec" onClick={onRemove}>Choose a different file</button>
                  <button className="btn sec" onClick={onKeep}>{r.outcome === "mismatched" ? "Upload anyway, as Other" : "Upload it anyway"}</button>
                </div>
              )}
            </>
          )}
        </span>
        <button className="xbtn" onClick={onRemove} aria-label="Remove"><Icon name="x" /></button>
      </div>
    </div>
  );
}

export function DocCard({ doc, onOpen, mode, applicationId, onChanged }: {
  doc: DocumentSummary; onOpen: (id: string) => void;
  mode?: "application" | "vault"; applicationId?: string; onChanged?: () => void;
}) {
  const [working, setWorking] = useState(false);
  const toast = useToast();
  const apps = applicationsOf(doc);
  // In an application, what matters is that application; in the vault, whether any of them was submitted.
  const locked = mode === "application" ? apps.some(a => a.application_id === applicationId && a.status !== "draft")
    : apps.some(a => a.status !== "draft");
  async function act(action: "remove" | "delete" | "link") {
    const message = action === "remove"
      ? `Remove "${doc.original_name}" from this application? It stays in My Vault. Unconfirmed pre-filled values from this file will be removed.`
      : `Permanently delete "${doc.original_name}" from My Vault? ${apps.length ? `It will also be removed from ${apps.length === 1 ? "its application" : `all ${apps.length} applications it is in`}, including submitted ones. ` : ""}The file, extracted data and document index will be deleted. This cannot be undone.`;
    if (action !== "link" && !window.confirm(message)) return;
    setWorking(true);
    try {
      if(action === "remove") await api.unlink(doc.file_id, applicationId);
      else if(action === "delete") await api.deleteDocument(doc.file_id);
      else if(applicationId) await api.linkDocument(doc.file_id, applicationId);
      toast(action === "remove" ? "Removed from application. Your vault copy is kept." : action === "delete" ? "Document permanently deleted." : "Document added to application.", "ok");
      onChanged?.();
    } catch(e) { toast(e instanceof ApiError ? e.message : "Could not update this document."); }
    finally { setWorking(false); }
  }
  const chip = <DocStatus doc={doc} />;
  const cls = doc.classification;
  const suggested = doc.document_tag === "other" && cls?.outcome === "mismatched" && LOAN_TYPES.includes(cls.detected_type) ? cls.detected_type : null;
  async function retype(tag: string) {
    setWorking(true);
    try { await vault.changeType(doc.file_id, tag); toast(`Saved as ${kindOf(tag).name}. We are reading its details now.`, "ok"); onChanged?.(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Could not change the type."); }
    finally { setWorking(false); }
  }

  return (
    <div className={`document-card document-type-${doc.document_tag}`}>
    <button className="vcard" onClick={() => onOpen(doc.file_id)}>
      <span className="vt"><Icon name={CATEGORY_ICON[doc.document_tag] ?? "doc"} /></span>
      <span className="vb">
        <b title={doc.original_name}>{doc.original_name}</b>
        <span>{doc.label ?? doc.display_name} &middot; {bytes(doc.size_bytes)}</span>
        {doc.classification && <span>AI detected: {TYPE_LABELS[doc.classification.detected_type] ?? doc.classification.detected_type.replaceAll("_", " ")}</span>}
        <span>{doc.extracted_field_count} fields read{doc.missing_field_count > 0 ? ` · ${doc.missing_field_count} missing` : ""}</span>
        <span style={{ display: "block", marginTop: 8 }}>{chip}</span>
      </span>
    </button>
    {mode && <div className="document-actions">
      <button className="btn sec doc-preview-action" onClick={() => onOpen(doc.file_id)}><Icon name="eye" />Preview</button>
      {mode === "application" && suggested && !locked && <button className="btn" disabled={working} onClick={() => void retype(suggested)}>Make it a {kindOf(suggested).name}</button>}
      {mode === "application" ? <button className="btn sec" disabled={working || locked} onClick={() => void act("remove")}><Icon name="x" />Remove from application</button>
        : <>
          {applicationId && !isIn(doc, applicationId) && <button className="btn sec" disabled={working} onClick={() => void act("link")}>Use in application</button>}
          <button className="btn sec danger" disabled={working || ["queued","processing"].includes(doc.status)} onClick={() => void act("delete")}><Icon name="trash" />Delete permanently</button>
        </>}
      {locked && <small className="hint">Linked to a submitted application</small>}
    </div>}
    </div>
  );
}

/** One status chip, shared by the application cards and the vault table. */
export function DocStatus({ doc }: { doc: DocumentSummary }) {
  // A file the customer moved from Other to the type HomeFlow saw counts as matched.
  const outcome = doc.classification?.detected_type === doc.document_tag ? "matched" : doc.classification?.outcome;
  if (doc.status === "processing" || doc.status === "queued") return <span className="chip n">Reading it now</span>;
  if (doc.status === "failed") return <span className="chip r"><Icon name="alert" />Could not read</span>;
  if (outcome === "unreadable" && !doc.extracted_field_count) return <span className="chip w"><Icon name="alert" />Saved · unreadable</span>;
  if (doc.status === "completed" && doc.missing_field_count > 0) return <span className="chip w"><Icon name="alert" />Fields need review</span>;
  if (doc.status === "completed" && doc.searchable === false) return <span className="chip w" title="Open it and choose Retry reading"><Icon name="alert" />Not searchable yet</span>;
  if (doc.classification?.mixed_document) return <span className="chip w"><Icon name="alert" />Several documents</span>;
  if (doc.document_tag === "other" && outcome === "mismatched") return <span className="chip w"><Icon name="info" />{doc.classification?.selected_type !== "other" ? "Saved as Other" : "Type suggested"}</span>;
  if (outcome === "matched" && doc.document_tag !== "other") return <span className="chip g"><Icon name="check" />{doc.application_id ? "Document type matched" : "Identified"}</span>;
  if (doc.document_tag === "other" && doc.status === "completed") return <span className="chip g"><Icon name="check" />Saved · searchable</span>;
  if (outcome) return <span className="chip w"><Icon name="alert" />Needs a look</span>;
  return <span className="chip n">Stored</span>;
}

/** Small drawing of each document type, shown on its tile once a file is in. */
function TileArt({ tag }: { tag: string }) {
  if (tag === "drivers_license" || tag === "ssn_card") {
    return (
      <svg width="96" height="64" viewBox="0 0 96 64" fill="none">
        <rect x="1" y="1" width="94" height="62" rx="9" fill="#fff" stroke="#a9d9c2" strokeWidth="1.5" />
        {tag === "drivers_license" ? <circle cx="24" cy="26" r="10" fill="#d8f3e6" /> : <rect x="14" y="16" width="20" height="20" rx="4" fill="#d8f3e6" />}
        <rect x="44" y="18" width="38" height="5" rx="2.5" fill="#0e6b5c" />
        <rect x="44" y="28" width="26" height="4" rx="2" fill="#d5e3dc" />
        <rect x="14" y="46" width="68" height="4" rx="2" fill="#d5e3dc" />
      </svg>
    );
  }
  const accent = tag === "w2" ? <><rect x="11" y="11" width="16" height="10" rx="2" fill="#0e6b5c" /><rect x="30" y="11" width="15" height="10" rx="2" fill="#d8f3e6" /></>
    : tag === "bank_statement" ? <><rect x="11" y="11" width="22" height="5" rx="2.5" fill="#0e6b5c" /><rect x="11" y="48" width="34" height="7" rx="3.5" fill="#c9f27b" /></>
    : <><rect x="11" y="11" width="26" height="5" rx="2.5" fill="#0e6b5c" /><rect x="11" y="52" width="18" height="6" rx="3" fill="#c9f27b" /></>;
  return (
    <svg width="56" height="74" viewBox="0 0 56 74" fill="none">
      <rect x="1" y="1" width="54" height="72" rx="7" fill="#fff" stroke="#a9d9c2" strokeWidth="1.5" />
      {accent}
      <rect x="11" y="27" width="34" height="4" rx="2" fill="#d5e3dc" />
      <rect x="11" y="35" width="30" height="4" rx="2" fill="#d5e3dc" />
      {tag !== "bank_statement" && <rect x="11" y="43" width="34" height="4" rx="2" fill="#d5e3dc" />}
    </svg>
  );
}
