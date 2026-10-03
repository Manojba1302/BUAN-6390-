import { useEffect, useState } from "react";
import { auth } from "./api";
import { Icon } from "./icons";
import type { CustomerProfile } from "./api";

export function AuthPage({onAuthenticated}:{onAuthenticated:(user:CustomerProfile)=>void}) {
  const [token,setToken] = useState(() => new URLSearchParams(location.hash.slice(1)).get("reset") || "");
  const [mode,setMode]=useState(token ? "reset-password" : "login");
  const [email,setEmail]=useState(""); const [password,setPassword]=useState("");
  const [first,setFirst]=useState(""); const [last,setLast]=useState("");
  const [visible,setVisible]=useState(false);
  const [confirmation,setConfirmation]=useState(""); const [confirmVisible,setConfirmVisible]=useState(false);
  const [busy,setBusy]=useState(false); const [error,setError]=useState(""); const [message,setMessage]=useState("");
  useEffect(() => {
    // Capture first, then remove the secret from the URL after rendering.
    // State initializers must be pure: React StrictMode calls them twice.
    if(token) history.replaceState(null,"",location.pathname + location.search);
    const receiveReset = () => {
      const incoming = new URLSearchParams(location.hash.slice(1)).get("reset");
      if(!incoming) return;
      setToken(incoming);setMode("reset-password");setPassword("");setConfirmation("");setError("");setMessage("");
    };
    window.addEventListener("hashchange",receiveReset);
    return () => window.removeEventListener("hashchange",receiveReset);
  }, [token]);
  const creating=mode === "register" || mode === "reset-password";
  const rules=[{label:"9+ characters",ok:password.length>=9},{label:"Upper & lowercase",ok:/[A-Z]/.test(password)&&/[a-z]/.test(password)},{label:"A number",ok:/[0-9]/.test(password)},{label:"A symbol: ! @ # $ % &",ok:/[!-/:-@\[-`{-~]/.test(password)}];
  const title = mode === "register" ? "Your next chapter starts here." : mode === "forgot-password" ? "Let’s get you back in." : mode === "reset-password" ? "A fresh start." : "Welcome home.";
  function change(next:string){setMode(next);setPassword("");setConfirmation("");setConfirmVisible(false);setVisible(false);setError("");setMessage("");}
  async function submit(event:React.FormEvent){
    event.preventDefault();
    if(creating && !rules.every(rule=>rule.ok)){setError("Still needed: " + rules.filter(rule=>!rule.ok).map(rule=>rule.label).join(", "));return;}
    if(creating && password!==confirmation){setError("Passwords do not match. Please re-enter your password.");return;}
    setBusy(true);setError("");setMessage("");
    try {
      const body: Record<string,string> = mode === "register" ? {email,password,first_name:first,last_name:last} : mode === "reset-password" ? {token,password} : mode === "forgot-password" ? {email} : {email,password};
      const result=await auth.submit(mode,body);
      if(mode === "login" || mode === "register") onAuthenticated(result);
      else {setMessage(result.message || "Request completed.");if(mode === "reset-password"){setMode("login");setToken("");setPassword("");setConfirmation("");setVisible(false);}}
    } catch(err){setError(err instanceof Error ? err.message : "Please try again.");} finally{setBusy(false);}
  }
  return <div className="entry-layout">
    <aside className="entry-photo">
      <div className="entry-brand"><Icon name="homeflow"/><div>HomeFlow<small>Your path home</small></div></div>
      <div className="entry-story"><span className="entry-kicker">A place to call yours</span><h2>Big plans.<br/>A simpler path home.</h2><p>Your application, documents and next steps. Together.</p></div>
      <img className="entry-home" src="/homeflow-family-home.png" alt="A family approaching their American-style home"/>
      <div className="entry-caption"><Icon name="home"/><span>From the first step to your front door.</span></div>
    </aside>
    <main className="main">
      <div className="auth-content"><p className="eyebrow">HOME STARTS WITH YOU</p><h1 className="h1">{title}</h1><p className="lede">{mode==="forgot-password" ? "Enter your email and we’ll send a password reset link." : mode==="reset-password" ? "Choose a new password for your HomeFlow account." : "One account. Everything you need for your home journey."}</p>
      {(mode==="login"||mode==="register")&&<div className="auth-tabs" aria-label="Account options"><button type="button" aria-pressed={mode==="login"} disabled={busy} onClick={()=>change("login")}>Sign in</button><button type="button" aria-pressed={mode==="register"} disabled={busy} onClick={()=>change("register")}>Create account</button></div>}
      <form className="card auth-form" onSubmit={submit}>
        {mode === "register" && <div className="grid g2"><label className="f">First name<input className="ctl" autoComplete="given-name" required maxLength={80} value={first} onChange={e=>setFirst(e.target.value)}/></label><label className="f">Last name<input className="ctl" autoComplete="family-name" required maxLength={80} value={last} onChange={e=>setLast(e.target.value)}/></label></div>}
        {mode !== "reset-password" && <label className="f">Email address<input className="ctl" type="email" autoComplete="email" placeholder="you@example.com" required value={email} onChange={e=>setEmail(e.target.value)}/></label>}
        {mode !== "forgot-password" && <div className="auth-password"><label className="f" htmlFor="account-password">{mode === "reset-password" ? "New password" : "Password"}</label><div className="auth-password-input"><input id="account-password" className="ctl" type={visible?"text":"password"} autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={creating?9:1} maxLength={128} required value={password} onChange={e=>setPassword(e.target.value)}/><button type="button" aria-label={visible?"Hide password":"Show password"} aria-pressed={visible} onClick={()=>setVisible(!visible)}>{visible?"Hide":"Show"}</button></div>{creating&&<ul className="password-rules" aria-label="Password requirements">{rules.map(rule=><li key={rule.label} className={rule.ok?"met":""}><span aria-hidden="true">{rule.ok?"✓":"○"}</span>{rule.label}</li>)}</ul>}</div>}
        {creating&&<><p className="password-feedback" aria-live="polite">{password && !rules.every(rule=>rule.ok) ? "Still needed: " + rules.filter(rule=>!rule.ok).map(rule=>rule.label).join(", ") : "Use 9+ characters with uppercase, lowercase, a number and a keyboard symbol."}</p><div className="auth-password"><label className="f" htmlFor="confirm-password">Confirm password</label><div className="auth-password-input"><input id="confirm-password" className="ctl" type={confirmVisible?"text":"password"} autoComplete="new-password" required maxLength={128} aria-invalid={confirmation.length>0&&confirmation!==password} aria-describedby="password-match" value={confirmation} onChange={e=>setConfirmation(e.target.value)}/><button type="button" aria-label={confirmVisible?"Hide confirm password":"Show confirm password"} aria-pressed={confirmVisible} onClick={()=>setConfirmVisible(!confirmVisible)}>{confirmVisible?"Hide":"Show"}</button></div><p id="password-match" className={confirmation ? (confirmation===password?"password-match met":"password-match mismatch") : "password-match"} aria-live="polite">{confirmation ? (confirmation===password?"Passwords match":"Passwords do not match yet.") : "Enter the same password again."}</p></div></>}
        {mode==="login"&&<div className="auth-recovery"><button type="button" className="linkish" disabled={busy} onClick={()=>change("forgot-password")}>Forgot password?</button></div>}
        {error && <p role="alert" className="err">{error}</p>}{message && <p role="status" className="hint">{message}</p>}
        <button className="btn wide auth-submit" disabled={busy}>{busy ? "Please wait…" : mode === "register" ? "Create my account" : mode === "forgot-password" ? "Send reset link" : mode === "reset-password" ? "Update password" : "Sign in"}<span aria-hidden="true">→</span></button>
        {(mode==="forgot-password"||mode==="reset-password")&&<div className="auth-links"><button type="button" className="linkish" disabled={busy} onClick={()=>change("login")}>Back to sign in</button></div>}
      </form><p className="auth-footnote">Your place to organize documents, save your progress and pick up where you left off.</p></div>
    </main>
  </div>;
}
