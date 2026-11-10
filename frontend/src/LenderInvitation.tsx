import { useEffect, useState } from "react";
import { api } from "./api";

export function LenderInvitation({onAccepted}: {onAccepted:(id:string)=>void}) {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("lender-invite"));
  const [info,setInfo] = useState<{lender:string; officer:string} | null>(null);
  const [message,setMessage] = useState("");
  const [busy,setBusy] = useState(false);
  const [done,setDone] = useState(false);
  useEffect(() => {
    if (!token) return;
    let active = true;
    api.lenderInvitation(token).then(value => {if (active) setInfo(value);})
      .catch(error => {if (active) setMessage(error.message);});
    return () => {active=false;};
  },[token]);
  if (!token) return null;
  async function confirm() {
    if (!token) return;
    setBusy(true);
    try {
      const result=await api.lenderInvitation(token,true);
      setDone(true);
      setMessage("Application started.");
      window.history.replaceState(null,"",window.location.pathname+window.location.search);
      if(result.application_id) onAccepted(result.application_id);
    } catch(error) { setMessage(error instanceof Error ? error.message : "Try again."); }
    finally {setBusy(false);}
  }
  return <section className="card"><h2>Start your lender application</h2>
    {info && !done && <><p>{info.officer} at {info.lender} invited you to start a new application. You choose which documents to send.</p>
    <button disabled={busy} onClick={()=>void confirm()}>Accept and start application</button></>}
    <p role="status">{message || (!info ? "Checking invitation…" : "")}</p></section>;
}
