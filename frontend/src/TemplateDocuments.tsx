import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Icon } from "./icons";

type Preview = {markdown:string; missing_fields:string[]; version:string};
export function TemplateDocuments({applicationId,onClose}:{applicationId:string;onClose:()=>void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const documentUrl = useRef<string|null>(null);
  const requestId = useRef(0);
  const [templates,setTemplates] = useState<{template_id:string;name:string}[]>([]);
  const [selected,setSelected] = useState("application-summary");
  const [preview,setPreview] = useState<Preview|null>(null);
  const [pages,setPages] = useState<string[]>([]);
  const [showPreview,setShowPreview] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const [busy,setBusy] = useState<"preview"|"download"|null>(null);
  useEffect(()=>{
    let active=true;
    dialog.current?.showModal();
    void api.documentTemplates().then(items=>{if(active)setTemplates(items);}).catch(e=>{if(active)setError(String(e));});
    return ()=>{active=false;requestId.current++;if(documentUrl.current)URL.revokeObjectURL(documentUrl.current);};
  },[]);
  function resetTemplate(value:string) {
    requestId.current++;
    if(documentUrl.current)URL.revokeObjectURL(documentUrl.current);
    documentUrl.current=null;setPages([]);setPreview(null);setShowPreview(false);
    setError("");setNotice("");setSelected(value);
  }
  async function generate(action:"preview"|"download") {
    const id=++requestId.current;
    setBusy(action);setError("");setNotice("");
    try {
      let url=documentUrl.current;
      if(!url) {
        const details=await api.renderTemplate(applicationId,selected);
        const blob=new Blob([Uint8Array.from(atob(details.pdf_base64),char=>char.charCodeAt(0))],{type:"application/pdf"});
        if(id!==requestId.current)return;
        url=URL.createObjectURL(blob);documentUrl.current=url;setPages(details.pages);setPreview(details);
      }
      if(action==="preview")setShowPreview(true);
      else {
        const link=document.createElement("a");link.href=url;link.download=`homeflow-${selected}-sample.pdf`;
        document.body.appendChild(link);link.click();link.remove();
        setNotice("Download started. You can preview the same PDF here.");
      }
    } catch(e) {if(id===requestId.current)setError(e instanceof Error?e.message:String(e));}
    finally {if(id===requestId.current)setBusy(null);}
  }
  return <dialog ref={dialog} className="document-chat template-generator" onCancel={onClose} aria-labelledby="template-title">
    <header className="chat-header"><span className="assistant-mark"><Icon name="doc"/></span><div><h2 id="template-title">Generate a document</h2><p>Preview or download your application summary</p></div><button className="panel-close" onClick={onClose} aria-label="Close document generator"><Icon name="x"/></button></header>
    <div className="chat-thread">
      <p className="hint">Uses saved, confirmed application details. Missing information is marked in the sample PDF.</p>
      <label className="cap" htmlFor="template-choice">Template</label>
      <select id="template-choice" className="ctl" value={selected} disabled={!!busy||!templates.length} onChange={e=>resetTemplate(e.target.value)}>{templates.map(t=><option key={t.template_id} value={t.template_id}>{t.name}</option>)}</select>
      {error&&<p role="alert" className="chat-error">{error}</p>}
      {notice&&<p role="status">{notice}</p>}
      {preview&&<p role="status" className={preview.missing_fields.length?"template-warning":"hint"}>{preview.missing_fields.length?`Missing or unconfirmed: ${preview.missing_fields.map(field=>field.replaceAll("_"," ")).join(", ")}. These are marked in your PDF.`:"All sample fields are populated."}</p>}
      {showPreview&&pages.length>0?<section className="template-pdf-preview" aria-label="PDF preview">{pages.map((page,index)=><figure key={index}><img src={`data:image/png;base64,${page}`} alt={`Application summary PDF, page ${index+1}`} /><figcaption>Page {index+1} of {pages.length}</figcaption></figure>)}<p className="hint">Preview and download show the same generated document.</p></section>:<div className="template-empty"><Icon name="doc"/><h3>Your document, ready when you are</h3><p>Download the PDF directly, or preview it here first.</p><small>Sample document - not an official disclosure or loan approval.</small></div>}
      {preview&&<details className="template-source"><summary>View Markdown source</summary><pre className="template-markdown">{preview.markdown}</pre></details>}
    </div>
    <footer className="chat-composer template-actions"><button className="btn ghost" disabled={!!busy||!templates.length} onClick={()=>void generate("preview")}>{busy==="preview"?"Preparing preview…":"Preview PDF"}</button><button className="btn" disabled={!!busy||!templates.length} onClick={()=>void generate("download")}>{busy==="download"?"Preparing download…":"Download PDF"}</button></footer>
  </dialog>;
}
