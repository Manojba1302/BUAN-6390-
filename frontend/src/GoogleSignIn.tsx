import {useEffect, useRef, useState} from "react";
import {auth, ApiError, type CustomerProfile} from "./api";
import {Icon} from "./icons";
type GIS = {initialize:(options:Record<string,unknown>)=>void;renderButton:(element:HTMLElement,options:Record<string,unknown>)=>void};
declare global {interface Window {google?: {accounts:{id:GIS}}}}
let loading: Promise<void> | undefined;
function loadGoogle() {
  if(window.google) return Promise.resolve();
  return loading ??= new Promise<void>((resolve,reject)=>{
    const script=document.createElement("script");script.src="https://accounts.google.com/gsi/client";
    script.async=true;script.onload=()=>resolve();script.onerror=()=>{script.remove();loading=undefined;reject(new Error("Google sign-in could not load. Use email and password, or try again later."));};
    document.head.appendChild(script);
  });
}
/** "Continue with Google" at the top of the sign-in card, then "or with email". Hidden until Google is configured and loaded. */
export function GoogleSignIn({onAuthenticated, mode}:{onAuthenticated:(user:CustomerProfile)=>void; mode:"login"|"register"}) {
  const authenticated=useRef(onAuthenticated); authenticated.current=onAuthenticated;
  const [attempt,setAttempt]=useState(0);
  const host=useRef<HTMLDivElement>(null),password=useRef("");
  const [error,setError]=useState(""),[link,setLink]=useState(false),[busy,setBusy]=useState(false),[ready,setReady]=useState(false);
  useEffect(()=>{
    let cancelled=false;
    async function setup(){
      // No answer about Google (older server, offline): email sign-in alone, no error box.
      const config=await auth.googleConfig().catch(()=>({client_id:""}));if(!config.client_id||cancelled)return;
      await loadGoogle();if(cancelled)return;
      const {nonce}=await auth.googleChallenge();if(cancelled||!host.current)return;
      window.google!.accounts.id.initialize({client_id:config.client_id,nonce,auto_select:false,callback:async ({credential}:{credential:string})=>{
        setBusy(true);setError("");
        try {const user=await auth.googleLogin(credential,password.current);password.current="";if(!cancelled)authenticated.current(user);}
        catch(e){if(!cancelled){setError(e instanceof Error?e.message:"Google sign-in failed.");setLink(current=>current || (e instanceof ApiError && e.status===409 && e.message.includes("existing HomeFlow password")));await setup().catch(()=>setError("Please refresh to try Google again."));}}
        finally {if(!cancelled)setBusy(false);}
      }});
      // Google draws its own button; match the card: full width (Google allows up to 400px), pill shaped, centred.
      const width=Math.round(Math.min(400,Math.max(220,host.current.closest("form")?.clientWidth ?? 360)-2));
      host.current.replaceChildren();window.google!.accounts.id.renderButton(host.current,{theme:"outline",size:"large",shape:"pill",text:mode==="register"?"signup_with":"continue_with",logo_alignment:"center",width});
      setReady(true);
    }
    setup().catch(e=>{if(!cancelled)setError(e instanceof Error?e.message:"Google sign-in unavailable.");});
    return ()=>{cancelled=true;};
  },[attempt,mode]);
  return <div className={`google-sign-in ${ready||error?"":"pending"}`} aria-busy={busy}>
    <div ref={host} className="google-button" style={{pointerEvents:busy?"none":undefined}}/>
    {busy&&<p role="status" className="google-status"><span className="spin"/>Signing you in with Google…</p>}
    {error&&<div className="google-error" role="alert"><Icon name="alert"/><span>{error}</span><button type="button" className="linkish" disabled={busy} onClick={()=>{setError("");setAttempt(n=>n+1);}}>Try Google again</button></div>}
    {link&&<label className="f google-link">Your HomeFlow password
      <input className="ctl" type="password" autoComplete="current-password" maxLength={128} onChange={e=>{password.current=e.target.value;}} onKeyDown={e=>{if(e.key==="Enter")e.preventDefault();}}/>
      <small>Asked once, to link Google to the account you already have. Then choose Google again.</small></label>}
    <p className="auth-or"><span>or with email</span></p>
  </div>;
}
