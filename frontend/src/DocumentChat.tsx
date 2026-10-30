import { useEffect, useRef, useState } from "react";
import { api, ApiError, type ChatReply, type SavedChatTurn } from "./api";
import { Icon } from "./icons";

type Reply = ChatReply;
type Turn = { question: string; reply?: Reply; error?: string; source_status?: Record<string, string>; draft?: string };

export function DocumentChat({ applicationId, minimized, onClose, onUnread, onOpenSource }: {
  applicationId: string; minimized: boolean; onClose: () => void; onUnread: () => void; onOpenSource: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const active = useRef<AbortController | null>(null);
  const minimizedNow = useRef(minimized);
  minimizedNow.current = minimized;
  const watchedPending = useRef<Set<string>>(new Set());
  const [elapsed, setElapsed] = useState(0);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [ended, setEnded] = useState(false);
  const storageKey = `homeflow-chat-session:${applicationId}`;
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<{conversation_id: string; created_at: string; updated_at: string; title: string; question_count: number}[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const boot = useRef<Promise<string> | null>(null);
  const sessionStarted = useRef(new Date().toISOString());
  function restore(items: SavedChatTurn[]) {
    const completed = items.some(item => watchedPending.current.has(item.turn_id) && item.status === "completed" && item.reply);
    watchedPending.current = new Set(items.filter(item => item.status === "pending").map(item => item.turn_id));
    if (completed && minimizedNow.current) onUnread();
    setTurns(items.map(item => ({question:item.question, reply:item.reply ?? undefined, error:item.error ?? undefined, source_status:item.source_status})));
    setPending(items.some(item => item.status === "pending"));
  }
  async function loadHistory(id: string, resume = false) {
    setLoading(true); setHistoryError("");
    try { if (resume) await api.resumeChatSession(id, sessionStarted.current); const history = await api.chatHistory(id); restore(history.turns); setConversationId(id); if (resume) setEnded(false); setShowHistory(false); setShowMenu(false); }
    catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        try {sessionStorage.removeItem(storageKey);} catch { /* Storage is optional. */ }
        setConversationId(null);setTurns([]);setEnded(true);setHistoryError("This conversation is no longer available. Start a conversation or select one from History.");
      } else setHistoryError(err instanceof Error ? err.message : "Could not load conversation");
    }
    finally { setLoading(false); }
  }
  useEffect(() => {
    let cancelled = false;
    let saved: {id?:string; started?:string; ended?:boolean} = {};
    try {saved = JSON.parse(sessionStorage.getItem(storageKey) || "{}");} catch { /* Storage is optional. */ }
    if (saved.started) sessionStarted.current = saved.started;
    setEnded(!!saved.ended);
    boot.current ??= saved.id ? Promise.resolve(saved.id) : api.newConversation(applicationId).then(created => created.conversation_id);
    void boot.current.then(async id => { if (cancelled) return; await loadHistory(id, !!saved.id && !saved.ended); setConversations(await api.conversations(applicationId)); }).catch(err => { if (!cancelled) {setHistoryError(String(err));setLoading(false);} });
    return () => { cancelled = true; };
  }, [applicationId]);
  useEffect(() => {
    if (!pending || !conversationId || busy) return;
    const timer = window.setInterval(() => {void api.chatHistory(conversationId).then(history => restore(history.turns)).catch(() => setHistoryError("Could not refresh the pending answer. Reopen chat to retry."));}, 3000);
    return () => window.clearInterval(timer);
  }, [pending, conversationId, busy]);
  useEffect(() => {const started = sessionStarted.current; return () => {if (conversationId) void api.endChatSession(conversationId, started).catch(() => {});};}, [conversationId]);
  useEffect(() => {
    if (!conversationId) return;
    try {sessionStorage.setItem(storageKey, JSON.stringify({id:conversationId,started:sessionStarted.current,ended}));} catch { /* Storage is optional. */ }
  }, [conversationId, ended, storageKey]);
  async function newChat() {
    setLoading(true); setQuestion(""); sessionStarted.current = new Date().toISOString();
    try {const created = await api.newConversation(applicationId); await loadHistory(created.conversation_id);setEnded(false);setConversations(await api.conversations(applicationId));}
    catch (err) {setHistoryError(String(err));setLoading(false);}
  }
  async function deleteChat(id = conversationId) {
    if (!id || !window.confirm("Delete this entire conversation and all its messages? Uploaded documents will be kept.")) return;
    setLoading(true); setHistoryError("");
    try {
      await api.deleteConversation(id);
      if (id === conversationId) {
        setConversationId(null); setTurns([]); setPending(false); setEnded(true); setQuestion(""); setShowMenu(false);
        try {sessionStorage.removeItem(storageKey);} catch { /* Storage is optional. */ }
      }
      setConversations(await api.conversations(applicationId));
    } catch (err) {setHistoryError(err instanceof Error ? err.message : "Could not delete conversation");}
    finally {setLoading(false);}
  }
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    const panel = dialog.current;
    if (minimized) panel?.close(); else if (!panel?.open) panel?.show();
    if (minimized) return;
    function outside(event: PointerEvent) { if (panel && !panel.contains(event.target as Node)) onClose(); }
    function escape(event: KeyboardEvent) { if (event.key === "Escape") onClose(); }
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape);
    return () => {document.removeEventListener("pointerdown", outside);document.removeEventListener("keydown", escape);};
  }, [minimized, onClose]);
  async function endConversation() {
    if (!conversationId || busy || pending) return;
    try {await api.endChatSession(conversationId, sessionStarted.current);setEnded(true);setQuestion("");setShowMenu(false);}
    catch {setHistoryError("Could not end this conversation. Please try again.");}
  }
  useEffect(() => { if (!busy) return; const timer = window.setInterval(() => setElapsed(value => value + 1), 1000); return () => window.clearInterval(timer); }, [busy]);
  useEffect(() => { if (!turns.length && !busy) return; bottom.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [turns, busy]);
  async function ask(text = question) {
    const prompt = text.trim();
    if (ended || !prompt || busy || loading || pending || !conversationId) return;
    const controller = new AbortController(); active.current = controller;
    setElapsed(0); setBusy(true); setQuestion(""); setTurns(previous => [...previous, {question: prompt}]);
    try {
      const showDraft = (draft: string) => setTurns(previous => [...previous.slice(0, -1), {...previous[previous.length - 1], draft}]);
      const saved = await api.streamMessage(conversationId, prompt, showDraft, controller.signal, sessionStarted.current);
      const reply = saved.reply ?? undefined;
      if (reply && minimizedNow.current) onUnread();
      setTurns(previous => [...previous.slice(0, -1), {...previous[previous.length - 1], draft: undefined, reply, error: saved.error ?? undefined, source_status:saved.source_status}]);
    } catch (err) {
      const error = controller.signal.aborted ? "Request stopped. You can ask again." : err instanceof ApiError ? err.message : "We could not answer that. Please try again.";
      setTurns(previous => [...previous.slice(0, -1), {...previous[previous.length - 1], error}]);
    } finally { active.current = null; setBusy(false); void api.conversations(applicationId).then(setConversations).catch(() => {}); if (conversationId) void api.chatHistory(conversationId).then(history => restore(history.turns)).catch(() => {}); }
  }
  return <dialog ref={dialog} className="document-chat chat-workspace" onCancel={event => {event.preventDefault();onClose();}} aria-labelledby="chat-title">
    <header className="chat-header"><span className="assistant-mark"><Icon name="spark" /></span><div><h2 id="chat-title">HomeFlow assistant</h2><p><span className="chat-status-dot" />Your document workspace</p></div><button type="button" className="panel-close" aria-label="Minimize document assistant" title="Minimize chat" onClick={onClose}><span aria-hidden="true">-</span></button></header>
    <div className="chat-history-tools">
      <div className="chat-conversation-heading"><span className="chat-current-title" title={conversations.find(item => item.conversation_id === conversationId)?.title || "New conversation"}>{conversations.find(item => item.conversation_id === conversationId)?.title || "New conversation"}</span><small><i />{ended ? "Conversation ended" : busy || pending ? "Preparing answer" : "Active conversation"}</small></div>
      <div className="chat-toolbar-actions"><button type="button" aria-label="Conversation history" aria-expanded={showHistory} disabled={busy || loading || pending} onClick={() => {setShowHistory(!showHistory);setShowMenu(false);}}><Icon name="history" /><span>History</span></button>
      {turns.length > 0 && <div className="chat-menu-wrap"><button type="button" aria-label="Conversation options" aria-expanded={showMenu} disabled={busy || loading || pending} onClick={() => {setShowMenu(!showMenu);setShowHistory(false);}}><Icon name="more" /></button>{showMenu && <div className="chat-options" aria-label="Conversation actions">{turns.length > 0 && <button type="button" className="chat-delete" onClick={() => void deleteChat()}><Icon name="trash" />Delete conversation</button>}</div>}</div>}</div>
    </div>
    {showHistory && <section className="chat-history-list" aria-label="Conversation history">
      <div className="chat-history-heading"><div><strong>Conversation history</strong><small>Each entry contains the full discussion.</small></div><button type="button" aria-label="Close history" onClick={() => setShowHistory(false)}>×</button></div>
      {!conversations.length && <p className="hint">No saved conversations yet. Your questions and answers will appear here together.</p>}
      {conversations.map(item => <div className="chat-history-row" key={item.conversation_id}>
        <button type="button" className="chat-history-open" disabled={loading} aria-current={item.conversation_id === conversationId ? "true" : undefined} onClick={() => void loadHistory(item.conversation_id, true)}><b>{item.title}</b><small>{new Date(item.updated_at).toLocaleString()} · {item.question_count} {item.question_count === 1 ? "question" : "questions"}{item.conversation_id === conversationId ? " · Current" : ""}</small></button>
        <button type="button" className="chat-history-delete" aria-label={`Delete conversation: ${item.title}`} title="Delete entire conversation" disabled={busy || pending || loading} onClick={() => void deleteChat(item.conversation_id)}><Icon name="trash" /></button>
      </div>)}
    </section>}
    {historyError && <p className="chat-error" role="alert">{historyError}</p>}
    <div className="chat-thread" aria-live="polite" aria-busy={busy}>
      {loading && <p className="hint">Loading saved conversation…</p>}
      {!loading && !ended && !turns.length && <section className="chat-welcome"><span className="chat-welcome-icon"><Icon name="chat" /></span><p className="eyebrow">A little clarity, right here</p><h3>Your documents.<br />Easier to understand.</h3><p>Find a detail, check a number, or go straight to its source.</p><div className="chat-prompts">{[{title:"Check my income",text:"What pay rate and job title are printed on my pay slip?",icon:"wallet"},{title:"Review my statement",text:"What period does my bank statement cover?",icon:"doc"}].map(prompt => <button type="button" key={prompt.title} disabled={ended || busy || loading || pending || !conversationId} onClick={() => void ask(prompt.text)}><Icon name={prompt.icon} /><span><b>{prompt.title}</b><small>{prompt.text}</small></span><Icon name="chevron" /></button>)}</div></section>}
      {turns.map((turn, index) => <section className="chat-turn" key={index}><div className="chat-user-message">{turn.question}</div>{turn.draft && !turn.reply && <div className="chat-assistant-message chat-draft" aria-busy="true"><span className="chat-speaker"><Icon name="spark" />HomeFlow</span><p>{turn.draft}</p><small className="hint">Checking this against your documents…</small></div>}{turn.reply && <div className="chat-assistant-message"><span className="chat-speaker"><Icon name="spark" />HomeFlow</span><p>{turn.reply.answer}</p>{Object.values(turn.source_status ?? {}).some(status => status !== "current") && <p className="chat-history-notice">A source has changed or is no longer attached. This is a historical answer; ask again for current information.</p>}{turn.reply.citations.length > 0 && <div className="chat-sources"><small>Sources · verified references</small>{turn.reply.citations.map(source => <button type="button" disabled={turn.source_status?.[source.file_id] === "unavailable"} key={`${source.file_id}-${source.page}`} onClick={() => {if (turn.source_status?.[source.file_id] !== "unavailable") {onClose(); onOpenSource(source.file_id);}}}><Icon name="doc" /><span>{turn.reply?.evidence.find(item => item.file_id === source.file_id)?.original_name || "Document"}<small>Page {source.page} · View source</small></span><Icon name="chevron" /></button>)}</div>}</div>}{turn.reply?.document_links?.length ? <div className="chat-sources"><small>Open documents</small>{turn.reply.document_links.map(file => <button type="button" disabled={turn.source_status?.[file.file_id] === "unavailable"} key={file.file_id} onClick={() => {if (turn.source_status?.[file.file_id] !== "unavailable") {onClose(); onOpenSource(file.file_id);}}}><Icon name="doc" /><span>{file.original_name}<small>Open document to review</small></span><Icon name="chevron" /></button>)}</div> : null}{turn.error && <div className="chat-error" role="alert"><Icon name="alert" /><p>{turn.error}</p><button type="button" disabled={ended || busy || loading || pending || !conversationId} onClick={() => void ask(turn.question)}>Try again</button></div>}</section>)}
      {(busy || pending) && !turns[turns.length - 1]?.draft && <div className="chat-thinking"><span className="spin" />{elapsed < 5 ? "Checking your documents…" : elapsed < 20 ? "Searching document details…" : "Preparing an answer — this can take up to two minutes…"}{busy && <button type="button" className="fchip" onClick={() => active.current?.abort()}>Stop waiting</button>}</div>}<div ref={bottom} />
    </div>
    <footer className="chat-composer">{ended ? <div className="chat-ended" role="status"><strong>{conversationId ? "Conversation ended" : "Conversation deleted"}</strong><p>{conversationId ? "Your messages are saved in History." : "Start a new conversation or open another one from History."}</p><button type="button" className="btn" disabled={loading} onClick={() => void newChat()}>Start conversation</button></div> : <><form onSubmit={event => { event.preventDefault(); void ask(); }}><label className="sr-only" htmlFor="document-question">Ask about your documents</label><textarea id="document-question" rows={2} maxLength={2000} value={question} onChange={event => setQuestion(event.target.value)} placeholder="Ask about your documents…" onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(); } }} /><button type="submit" disabled={busy || loading || pending || !conversationId || !question.trim()} aria-label="Send question"><Icon name="send" /></button></form><div className="chat-footer-actions"><small>Minimize to continue later</small><button type="button" className="chat-end-action" disabled={busy || loading || pending || !conversationId} onClick={() => void endConversation()}>End conversation</button></div></>}</footer>
  </dialog>;
}
