/** The review screen: the document on one side, what we read on the other.
 *
 *  A correction never destroys the original reading, and sensitive values stay
 *  masked until the customer asks to see them.
 */
import { useEffect, useState } from "react";

import { api } from "./api";
import { fieldLabelFromName, maskSensitive } from "./format";
import { Icon } from "./icons";
import { useToast } from "./ui";
import type { DocumentDetail } from "./types";

const SENSITIVE = ["ssn", "employee_ssn", "account_mask", "license_number"];

export function DocDrawer({ fileId, onClose, onSaved }: {
  fileId: string | null; onClose: () => void; onSaved: () => void;
}) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  useEffect(() => {
    if (!fileId) { setDoc(null); return; }
    setEdits({});
    setRevealed({});
    api.document(fileId).then(setDoc).catch(() => toast("We could not open that document."));
  }, [fileId, toast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function save() {
    if (!doc) return;
    const corrections = Object.entries(edits)
      .filter(([id, value]) => {
        const row = doc.extractions.find((e) => e.extraction_id === id);
        return row && value !== (row.value ?? "");
      })
      .map(([extraction_id, value]) => ({ extraction_id, value }));

    if (!corrections.length) { onClose(); return; }
    setSaving(true);
    try {
      await api.correct(doc.file_id, corrections);
      toast(`${corrections.length} correction${corrections.length > 1 ? "s" : ""} saved`, "ok");
      onSaved();
      onClose();
    } catch {
      toast("We could not save those corrections.");
    } finally {
      setSaving(false);
    }
  }

  const open = Boolean(fileId);

  return (
    <>
      <div className={`scrim ${open ? "on" : ""}`} onClick={onClose} />
      <aside className={`drawer ${open ? "on" : ""}`} role="dialog" aria-modal="true"
             aria-labelledby="drawerTitle">
        {doc && (
          <>
            <div className="dr-head">
              <b id="drawerTitle">{doc.original_name}</b>
              {doc.classification && (
                <span className={`chip ${doc.classification.outcome === "matched" ? "g" : "w"}`}>
                  <Icon name={doc.classification.outcome === "matched" ? "check" : "alert"} />
                  {doc.classification.outcome === "matched" ? "Matched" : "Check this"}
                </span>
              )}
              <button className="xbtn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
            </div>

            <div className="dr-body">
              <div className="dr-doc">
                <div className="page">
                  {doc.content_type?.startsWith("image/")
                    ? <img src={api.contentUrl(doc.file_id)} alt="Your uploaded document" />
                    : <iframe title="Your uploaded document" src={api.contentUrl(doc.file_id)}
                              style={{ width: "100%", height: "60vh", border: 0 }} />}
                </div>
              </div>

              <div className="dr-fields">
                <p className="hint" style={{ marginBottom: 12 }}>
                  What we read from this document. Change anything that is wrong: your
                  correction is what counts from then on.
                </p>

                {doc.status !== "completed" && (
                  <div className="banner" style={{ marginTop: 0 }}>
                    <Icon name="info" />
                    <div>
                      <b>Still being read</b>
                      This page fills in as soon as the document has been processed.
                    </div>
                  </div>
                )}

                {doc.extractions.map((row) => {
                  const sensitive = SENSITIVE.includes(row.field_name);
                  const shown = edits[row.extraction_id] ?? row.value ?? "";
                  const display = sensitive && !revealed[row.extraction_id]
                    ? maskSensitive(shown) : shown;
                  return (
                    <div className="fieldrow" key={row.extraction_id}>
                      <div className="fr-top">
                        <b>{fieldLabelFromName(row.field_name)}</b>
                        <span className="chip n">{row.method === "native_text" ? "text" : row.method}</span>
                        {row.review_state === "corrected" && <span className="chip a">corrected</span>}
                        {sensitive && (
                          <button className="xbtn" aria-label="Show value"
                                  onClick={() => setRevealed((r) =>
                                    ({ ...r, [row.extraction_id]: !r[row.extraction_id] }))}>
                            <Icon name="eye" />
                          </button>
                        )}
                      </div>
                      <input className={`ctl ${sensitive && !revealed[row.extraction_id] ? "mask" : ""}`}
                             value={display}
                             readOnly={sensitive && !revealed[row.extraction_id]}
                             onChange={(e) => setEdits((x) =>
                               ({ ...x, [row.extraction_id]: e.target.value }))} />
                      {row.evidence_quote && (
                        <div className="evid">
                          Found on page {row.page ?? 1}: <code>{row.evidence_quote}</code>
                        </div>
                      )}
                    </div>
                  );
                })}

                {doc.missing_fields.length > 0 && (
                  <div className="missingbox">
                    <b><Icon name="alert" /> We could not find {doc.missing_fields.length} thing
                      {doc.missing_fields.length > 1 ? "s" : ""}</b>
                    <ul>{doc.missing_fields.map((f) => <li key={f}>{fieldLabelFromName(f)}</li>)}</ul>
                    <p style={{ fontSize: 13, marginTop: 8 }}>
                      We leave these blank rather than guess. You can type them in the form yourself.
                    </p>
                  </div>
                )}

                <div style={{ marginTop: 18, display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button className="btn" onClick={() => void save()} disabled={saving}>
                    {saving ? "Saving" : "Save corrections"}
                  </button>
                  <button className="btn sec" onClick={onClose}>Close</button>
                </div>
              </div>
            </div>
          </>
        )}
      </aside>
    </>
  );
}
