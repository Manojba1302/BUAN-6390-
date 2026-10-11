import { useEffect, useRef, useState } from "react";
import { api, ApiError, type ChatReply, type SavedChatTurn } from "./api";
import { Icon } from "./icons";

type Reply = ChatReply;
type Turn = { question: string; reply?: Reply; error?: string; source_status?: Record<string, string> };

export function DocumentChat({ applicationId, onClose, onOpenSource }: {
  applicationId: string; onClose: () => void; onOpenSource: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const active = useRef<AbortController | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<{conversation_id: string; created_at: string; updated_at: string; title: string}[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const boot = useRef<Promise<string> | null>(null);
  function restore(items: SavedChatTurn[]) {
    setTurns(items.map(item => ({question:item.question, reply:item.reply ?? undefined, error:item.error ?? undefined, source_status:item.source_status})));
    setPending(items.some(item => item.status === "pending"));
  }
  async function loadHistory(id: string) {
    setLoading(true); setHistoryError("");
    try { const history = await api.chatHistory(id); restore(history.turns); setConversationId(id); setShowHistory(false); setShowMenu(false); }
    catch (err) { setHistoryError(err instanceof Error ? err.message : "Could not load conversation"); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    let cancelled = false;
    boot.current ??= api.conversations(applicationId).then(async list => { if (list.length) return list[0].conversation_id; return (await api.newConversation(applicationId)).conversation_id; });
    void boot.current.then(async id => { if (cancelled) return; await loadHistory(id); setConversations(await api.conversations(applicationId)); }).catch(err => { if (!cancelled) {setHistoryError(String(err));setLoading(false);} });
    return () => { cancelled = true; };
  }, [applicationId]);
  useEffect(() => {
    if (!pending || !conversationId || busy) return;
    const timer = window.setInterval(() => {void api.chatHistory(conversationId).then(history => restore(history.turns)).catch(() => setHistoryError("Could not refresh the pending answer. Reopen chat to retry."));}, 3000);
    return () => window.clearInterval(timer);
  }, [pending, conversationId, busy]);
  async function newChat() {
    setLoading(true);
    try {const created = await api.newConversation(applicationId); await loadHistory(created.conversation_id);setConversations(await api.conversations(applicationId));}
    catch (err) {setHistoryError(String(err));setLoading(false);}
  }
  async function deleteChat() {
    if (!conversationId || !window.confirm("Delete this conversation and its messages? Your documents will be kept.")) return;
    setLoading(true);
    try {await api.deleteConversation(conversationId);setConversationId(null);setTurns([]);setPending(false);const list = await api.conversations(applicationId);setConversations(list);if(list.length) await loadHistory(list[0].conversation_id);else {const created = await api.newConversation(applicationId);await loadHistory(created.conversation_id);setConversations(await api.conversations(applicationId));}}
    catch (err) {setHistoryError(String(err));setLoading(false);}
  }
  useEffect(() => { dialog.current?.showModal(); return () => active.current?.abort(); }, []);
  useEffect(() => { if (!busy) return; const timer = window.setInterval(() => setElapsed(value => value + 1), 1000); return () => window.clearInterval(timer); }, [busy]);
  useEffect(() => { bottom.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [turns, busy]);
  async function ask(text = question) {
    const prompt = text.trim();
    if (!prompt || busy || loading || pending || !conversationId) return;
    const controller = new AbortController(); active.current = controller;
    setElapsed(0); setBusy(true); setQuestion(""); setTurns(previous => [...previous, {question: prompt}]);
    try {
      const saved = await api.sendMessage(conversationId, prompt, controller.signal);
      const reply = saved.reply ?? undefined;
      setTurns(previous => [...previous.slice(0, -1), {...previous[previous.length - 1], reply, source_status:saved.source_status}]);
    } catch (err) {
      const error = controller.signal.aborted ? "Request stopped. You can ask again." : err instanceof ApiError ? err.message : "We could not answer that. Please try again.";
      setTurns(previous => [...previous.slice(0, -1), {...previous[previous.length - 1], error}]);
    } finally { active.current = null; setBusy(false); void api.conversations(applicationId).then(setConversations).catch(() => {}); if (conversationId) void api.chatHistory(conversationId).then(history => restore(history.turns)).catch(() => {}); }
  }
  return <dialog ref={dialog} className="document-chat" onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) { const bounds = event.currentTarget.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose(); } }} aria-labelledby="chat-title">
    <header className="chat-header"><span className="assistant-mark"><Icon name="spark" /></span><div><h2 id="chat-title">HomeFlow assistant</h2><p><span className="chat-status-dot" />Your document workspace</p></div><button type="button" className="panel-close" aria-label="Close document assistant" title="Close" onClick={onClose}><Icon name="x" /></button></header>
    <div className="chat-history-tools"><span className="chat-current-title">{conversations.find(item => item.conversation_id === conversationId)?.title || "New conversation"}</span><button type="button" disabled={busy || loading || pending} onClick={() => void newChat()}><Icon name="plus" /><span>New chat</span></button>{conversations.some(item => item.title !== "New conversation") && <button type="button" aria-expanded={showHistory} disabled={busy || loading || pending} onClick={() => {setShowHistory(!showHistory);setShowMenu(false);}}><Icon name="history" /><span>History</span></button>}{turns.length > 0 && <div className="chat-menu-wrap"><button type="button" aria-label="Conversation options" aria-expanded={showMenu} disabled={busy || loading || pending} onClick={() => {setShowMenu(!showMenu);setShowHistory(false);}}><Icon name="more" /></button>{showMenu && <div className="chat-options"><button type="button" onClick={() => void deleteChat()}><Icon name="trash" />Delete conversation</button></div>}</div>}</div>
    {showHistory && <section className="chat-history-list" aria-label="Conversation history"><div><strong>Your conversations</strong><button type="button" aria-label="Close history" onClick={() => setShowHistory(false)}>×</button></div>{conversations.map(item => <button type="button" key={item.conversation_id} aria-current={item.conversation_id === conversationId ? "true" : undefined} onClick={() => void loadHistory(item.conversation_id)}><b>{item.title}</b><small>{new Date(item.updated_at).toLocaleString()}</small></button>)}</section>}
    {historyError && <p className="chat-error" role="alert">{historyError}</p>}
    <div className="chat-thread" aria-live="polite" aria-busy={busy}>
      {loading && <p className="hint">Loading saved conversation…</p>}
      {!loading && !turns.length && <section className="chat-welcome"><span className="chat-welcome-icon"><Icon name="chat" /></span><p className="eyebrow">A little clarity, right here</p><h3>Your documents.<br />Easier to understand.</h3><p>Find a detail, check a number, or go straight to its source.</p><div className="chat-prompts">{[{title:"Check my income",text:"What pay rate and job title are printed on my pay slip?",icon:"wallet"},{title:"Review my statement",text:"What period does my bank statement cover?",icon:"doc"}].map(prompt => <button type="button" key={prompt.title} disabled={busy || loading || pending || !conversationId} onClick={() => void ask(prompt.text)}><Icon name={prompt.icon} /><span><b>{prompt.title}</b><small>{prompt.text}</small></span><Icon name="chevron" /></button>)}</div></section>}
      {turns.map((turn, index) => <section className="chat-turn" key={index}><div className="chat-user-message">{turn.question}</div>{turn.reply && <div className="chat-assistant-message"><span className="chat-speaker"><Icon name="spark" />HomeFlow</span><p>{turn.reply.answer}</p>{Object.values(turn.source_status ?? {}).some(status => status !== "current") && <p className="chat-history-notice">A source has changed or is no longer attached. This is a historical answer; ask again for current information.</p>}{turn.reply.citations.length > 0 && <div className="chat-sources"><small>Sources · verified references</small>{turn.reply.citations.map(source => <button type="button" disabled={turn.source_status?.[source.file_id] === "unavailable"} key={`${source.file_id}-${source.page}`} onClick={() => {if (turn.source_status?.[source.file_id] !== "unavailable") {onClose(); onOpenSource(source.file_id);}}}><Icon name="doc" /><span>{turn.reply?.evidence.find(item => item.file_id === source.file_id)?.original_name || "Document"}<small>Page {source.page} · View source</small></span><Icon name="chevron" /></button>)}</div>}</div>}{turn.reply?.document_links?.length ? <div className="chat-sources"><small>Open documents</small>{turn.reply.document_links.map(file => <button type="button" disabled={turn.source_status?.[file.file_id] === "unavailable"} key={file.file_id} onClick={() => {if (turn.source_status?.[file.file_id] !== "unavailable") {onClose(); onOpenSource(file.file_id);}}}><Icon name="doc" /><span>{file.original_name}<small>Open document to review</small></span><Icon name="chevron" /></button>)}</div> : null}{turn.error && <div className="chat-error" role="alert"><Icon name="alert" /><p>{turn.error}</p><button type="button" disabled={busy || loading || pending || !conversationId} onClick={() => void ask(turn.question)}>Try again</button></div>}</section>)}
      {(busy || pending) && <div className="chat-thinking"><span className="spin" />{elapsed < 5 ? "Checking your documents…" : elapsed < 20 ? "Searching document details…" : "Preparing an answer — this can take up to two minutes…"}{busy && <button type="button" className="fchip" onClick={() => active.current?.abort()}>Stop waiting</button>}</div>}<div ref={bottom} />
    </div>
    <footer className="chat-composer"><form onSubmit={event => { event.preventDefault(); void ask(); }}><label className="sr-only" htmlFor="document-question">Ask about your documents</label><textarea autoFocus id="document-question" rows={2} maxLength={2000} value={question} onChange={event => setQuestion(event.target.value)} placeholder="Ask about your documents…" onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(); } }} /><button type="submit" disabled={busy || loading || pending || !conversationId || !question.trim()} aria-label="Send question"><Icon name="send" /></button></form><small>Saved to your account · Answers linked to your documents</small></footer>
  </dialog>;
}
