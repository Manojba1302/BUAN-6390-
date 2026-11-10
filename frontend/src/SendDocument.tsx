import {useEffect,useState} from "react";
import {api} from "./api";
import type {DocumentSummary} from "./types";

export function SendDocument({app,documents}:{app:string;documents:DocumentSummary[]}) {
  const [targets,setTargets]=useState<{loan_id:string;lender:string;stage:string}[]|null>(null);
  const [loan,setLoan]=useState(""), [file,setFile]=useState(""), [message,setMessage]=useState("");
  const [busy,setBusy]=useState(false);
  const [requests,setRequests]=useState<Awaited<ReturnType<typeof api.documentRequests>>>([]);
  const [rid,setRid]=useState(""),[refresh,setRefresh]=useState(0);
  useEffect(()=>{let active=true;if(loan)api.documentRequests(app,loan).then(v=>{if(active)setRequests(v);}).catch(e=>{if(active)setMessage(e.message);});return()=>{active=false;};},[app,loan,refresh]);
  async function run(send:boolean) {
    setBusy(true); setMessage("");
    try {
      if(send) {
        const result=await api.sendDocument(app,loan,file,rid || undefined);
        setRid("");setRefresh(n=>n+1);
        setMessage(result.status==="already_sent"?"This version was already sent.":result.status==="sent_email_failed"?"Copy delivered. The email notification could not be delivered.":"Copy sent to the loan team.");
      } else {setTargets(await api.lenders(app));}
    } catch(e) {setMessage(e instanceof Error?e.message:"Please try again.");}
    finally {setBusy(false);}
  }
  return <section className="card send-lender"><h2>Share with your lender</h2>
    {targets===null?<button className="btn" disabled={busy} onClick={()=>void run(false)}>Choose a loan and document</button>:
    targets.length===0?<p>No lender is linked to this application.</p>:<>
    <label>Lender and loan<select className="ctl" value={loan} onChange={e=>{setLoan(e.target.value);setRequests([]);setRid("");setMessage("");}}>
      <option value="">Choose a destination</option>{targets.map(t=><option key={t.loan_id} value={t.loan_id}>{t.lender} · HD-{t.loan_id.slice(0,8).toUpperCase()}</option>)}</select></label>
    {loan && <p className="hint">Loan status: <strong>{targets.find(t=>t.loan_id===loan)?.stage}</strong></p>}
    {loan && <section aria-label="Requests from your loan team"><h3>Requests from your loan team</h3>
      <button className="btn sec" onClick={()=>setRefresh(n=>n+1)}>Refresh requests</button>
      {requests.map(r=><p key={r.request_id}>{r.title} · {r.status}{r.revision ? " · v"+r.revision : ""}{r.reason && <strong> · {r.reason}</strong>}</p>)}
      {requests.some(r=>r.status==="requested"||r.status==="rejected") && <label>Respond to request<select className="ctl" value={rid} onChange={e=>setRid(e.target.value)}>
      <option value="">Share separately</option>{requests.filter(r=>r.status==="requested"||r.status==="rejected").map(r=><option key={r.request_id} value={r.request_id}>{r.title}</option>)}</select></label>}
    </section>}
    <label>Attached document<select className="ctl" value={file} onChange={e=>{setFile(e.target.value);setMessage("");}}>
      <option value="">Choose a document</option>{documents.map(d=><option key={d.file_id} value={d.file_id}>{d.original_name}</option>)}</select></label>
    <p className="hint">Uploading or attaching a file doesn't send it. Your lender gets a copy only when you press Send, and keeps it even if you later change or delete the original.</p>
    <button className="btn" disabled={busy||!loan||!documents.some(d=>d.file_id===file)} onClick={()=>void run(true)}>Send to loan team</button></>}
    <p role="status">{message}</p></section>;
}
