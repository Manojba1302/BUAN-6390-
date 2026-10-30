/** Local preview first; server classification starts only after Submit. */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { api, ApiError } from "./api";
import { bytes } from "./format";
import { CATEGORY_ICON, Icon } from "./icons";
import { useToast } from "./ui";
import type { ChecklistItem, DocumentSummary, StagedFile } from "./types";

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

type CatState = { have: number; need: number; flagged: boolean; satisfied: boolean };

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
    const flagged = mine.some((d) => d.classification &&
      d.classification.outcome !== "matched");
    return { have: mine.length, need, flagged, satisfied: mine.length > 0 && mine.length >= need };
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
            const fill = s.have ? "has" : s.need ? "needed" : "optional";
            return (
              <button key={c.document_tag} className={`doctile ${cls} ${fill} doctype-${c.document_tag}`}
                      onClick={() => { setActiveCat(c.document_tag); discard(); }}>
                <span className="tile-art" aria-hidden="true">{s.have ? <TileArt tag={c.document_tag} /> : <Icon name="plus" />}</span>
                <span className="ti"><Icon name={CATEGORY_ICON[c.document_tag] ?? "doc"} /></span>
                <span className="tt">
                  <b>{c.display_name}</b>
                  <small className="document-guidance">{c.guidance}</small><span>{s.have ? (s.need ? `${s.have} of ${s.need} uploaded` : `${s.have} uploaded`) : (s.need ? `0 of ${s.need} uploaded` : "No files uploaded")}</span>
                </span>
                {s.flagged ? <span className="chip w"><Icon name="alert" />Needs a look</span>
                  : s.satisfied ? <span className="chip g"><Icon name="check" />Uploaded</span>
                  : s.have ? <span className="chip a">{s.have} of {s.need}</span>
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
        <p className="hint">Reuse an existing document without uploading another copy.</p>
        <button className="btn sec" onClick={() => setShowVault(!showVault)}>{showVault ? "Hide vault documents" : "Choose from My Vault"}</button>
        {showVault && <div className="vaultgrid" style={{marginTop:16}}>
          {props.vaultDocuments.filter(d => !d.application_id).map(d => <DocCard key={d.file_id} doc={d} onOpen={onOpenDoc} mode="vault" applicationId={applicationId} onChanged={onUploaded} />)}
          {!props.vaultDocuments.some(d => !d.application_id) && <p className="hint">No unattached documents yet. Documents removed from this application will appear here.</p>}
        </div>}
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
              {(r.outcome === "mismatched" || r.outcome === "unknown" || r.outcome === "failed") && !item.kept && (
                <div className="sitem-act">
                  <button className="btn sec" onClick={onRemove}>Choose a different file</button>
                  <button className="btn sec" onClick={onKeep}>Upload it anyway</button>
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
  const locked = Boolean(doc.application_status && doc.application_status !== "draft");
  async function act(action: "remove" | "delete" | "link") {
    const message = action === "remove"
      ? `Remove "${doc.original_name}" from this application? It stays in My Vault. Unconfirmed pre-filled values from this file will be removed.`
      : `Permanently delete "${doc.original_name}" from My Vault? ${doc.application_id ? "It will also be removed from its draft application. " : ""}The file, extracted data and document index will be deleted. This cannot be undone.`;
    if (action !== "link" && !window.confirm(message)) return;
    setWorking(true);
    try {
      if(action === "remove") await api.unlink(doc.file_id);
      else if(action === "delete") await api.deleteDocument(doc.file_id);
      else if(applicationId) await api.linkDocument(doc.file_id, applicationId);
      toast(action === "remove" ? "Removed from application. Your vault copy is kept." : action === "delete" ? "Document permanently deleted." : "Document added to application.", "ok");
      onChanged?.();
    } catch(e) { toast(e instanceof ApiError ? e.message : "Could not update this document."); }
    finally { setWorking(false); }
  }
  const outcome = doc.classification?.outcome;
  const chip =
    doc.status === "processing" || doc.status === "queued"
      ? <span className="chip n">Reading it now</span>
      : doc.status === "failed"
      ? <span className="chip r"><Icon name="alert" />Could not read</span>
      : doc.status === "completed" && doc.missing_field_count > 0
      ? <span className="chip w"><Icon name="alert" />Fields need review</span>
      : outcome === "matched"
      ? <span className="chip g"><Icon name="check" />Document type matched</span>
      : outcome
      ? <span className="chip w"><Icon name="alert" />Needs a look</span>
      : <span className="chip n">Stored</span>;

  return (
    <div className={`document-card document-type-${doc.document_tag}`}>
    <button className="vcard" onClick={() => onOpen(doc.file_id)}>
      <span className="vt"><Icon name={CATEGORY_ICON[doc.document_tag] ?? "doc"} /></span>
      <span className="vb">
        <b title={doc.original_name}>{doc.original_name}</b>
        <span>{doc.display_name} &middot; {bytes(doc.size_bytes)}</span>
        {doc.classification && <span>AI detected: {TYPE_LABELS[doc.classification.detected_type] ?? doc.classification.detected_type.replaceAll("_", " ")}</span>}
        <span>{doc.extracted_field_count} fields read{doc.missing_field_count > 0 ? ` · ${doc.missing_field_count} missing` : ""}</span>
        <span style={{ display: "block", marginTop: 8 }}>{chip}</span>
      </span>
    </button>
    {mode && <div className="document-actions">
      <button className="btn sec doc-preview-action" onClick={() => onOpen(doc.file_id)}><Icon name="eye" />Preview</button>
      {mode === "application" ? <button className="btn sec" disabled={working || locked} onClick={() => void act("remove")}><Icon name="x" />Remove from application</button>
        : <>
          {applicationId && !doc.application_id && <button className="btn sec" disabled={working} onClick={() => void act("link")}>Use in application</button>}
          <button className="btn sec danger" disabled={working || locked || ["queued","processing"].includes(doc.status)} onClick={() => void act("delete")}><Icon name="trash" />Delete permanently</button>
        </>}
      {locked && <small className="hint">Linked to a submitted application</small>}
    </div>}
    </div>
  );
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
