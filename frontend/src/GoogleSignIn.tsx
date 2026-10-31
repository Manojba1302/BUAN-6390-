import {useEffect, useRef, useState} from "react";
import {auth, ApiError, type CustomerProfile} from "./api";
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
export function GoogleSignIn({onAuthenticated}:{onAuthenticated:(user:CustomerProfile)=>void}) {
  const authenticated=useRef(onAuthenticated); authenticated.current=onAuthenticated;
  const [attempt,setAttempt]=useState(0);
  const host=useRef<HTMLDivElement>(null),password=useRef("");
  const [error,setError]=useState(""),[link,setLink]=useState(false),[busy,setBusy]=useState(false);
  useEffect(()=>{
    let cancelled=false;
    async function setup(){
      const config=await auth.googleConfig();if(!config.client_id||cancelled)return;
      await loadGoogle();if(cancelled)return;
      const {nonce}=await auth.googleChallenge();if(cancelled||!host.current)return;
      window.google!.accounts.id.initialize({client_id:config.client_id,nonce,auto_select:false,callback:async ({credential}:{credential:string})=>{
        setBusy(true);setError("");
        try {const user=await auth.googleLogin(credential,password.current);password.current="";if(!cancelled)authenticated.current(user);}
        catch(e){if(!cancelled){setError(e instanceof Error?e.message:"Google sign-in failed.");setLink(current=>current || (e instanceof ApiError && e.status===409 && e.message.includes("existing HomeFlow password")));await setup().catch(()=>setError("Please refresh to try Google again."));}}
        finally {if(!cancelled)setBusy(false);}
      }});
      host.current.replaceChildren();window.google!.accounts.id.renderButton(host.current,{theme:"outline",size:"large",text:"continue_with",width:300});
    }
    setup().catch(e=>{if(!cancelled)setError(e instanceof Error?e.message:"Google sign-in unavailable.");});
    return ()=>{cancelled=true;};
  },[attempt]);
  return <div className="google-sign-in"><div ref={host} style={{pointerEvents:busy?"none":undefined}}/>{busy&&<p role="status">Signing in…</p>}
    {error&&<><p role="alert">{error}</p><button type="button" disabled={busy} onClick={()=>{setError("");setAttempt(n=>n+1);}}>Retry Google sign-in</button></>}{link&&<label>Existing HomeFlow password<input type="password" autoComplete="current-password" maxLength={128} onChange={e=>{password.current=e.target.value;}}/></label>}</div>;
}
