'use client';

/**
 * ClarificationPopup — slide-out chat panel for answering an open
 * ContextRequest. Mounts globally (see DashboardProviders) but only
 * renders when `popupOpen` is true on the ClarificationCtx.
 *
 * Each open request becomes a focused chat: we POST `mode: 'clarify'`
 * to `/api/copilot/chat` with the request id pinned, the backend resolves
 * it via the `record_clarification_answer` tool, and once the LLM marks
 * the request answered the next poll drops it from the list.
 */

import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Send, X } from 'lucide-react';
import { useClarifications } from './ClarificationProvider';

interface ChatMsg {
  role: 'user' | 'assistant';
  content: string;
}

export function ClarificationPopup() {
  const { popupOpen, closePopup, requests, focusedId, setFocusedId, refresh } =
    useClarifications();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const open = requests.filter((r) => r.status === 'open');
  const focusIdx = focusedId ? open.findIndex((r) => r.id === focusedId) : 0;
  const focused = open[Math.max(0, focusIdx)] ?? null;

  useEffect(() => {
    if (!popupOpen || !focused) {
      setMessages([]);
      return;
    }
    setMessages([
      {
        role: 'assistant',
        content: `Quick clarification needed about ${focused.scope_ref}. Loading…`,
      },
    ]);
    fetch('/api/copilot/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: '',
        mode: 'clarify',
        clarification_request_id: focused.id,
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        const reply = data?.message ?? data?.reply ?? '...';
        setMessages([{ role: 'assistant', content: reply }]);
      })
      .catch(() => {
        setMessages([{ role: 'assistant', content: '(failed to load question)' }]);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [popupOpen, focused?.id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages]);

  if (!popupOpen) return null;

  const send = async () => {
    if (!input.trim() || !focused || sending) return;
    const userMsg: ChatMsg = { role: 'user', content: input };
    setMessages((m) => [...m, userMsg]);
    const trimmed = input;
    setInput('');
    setSending(true);
    try {
      const res = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: trimmed,
          mode: 'clarify',
          clarification_request_id: focused.id,
          history: [...messages, userMsg],
        }),
      });
      const data = await res.json();
      const reply = data?.message ?? data?.reply ?? '(no response)';
      setMessages((m) => [...m, { role: 'assistant', content: reply }]);
      await refresh();
    } catch {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: '(failed to send)' },
      ]);
    } finally {
      setSending(false);
    }
  };

  const goPrev = () => {
    if (focusIdx > 0) setFocusedId(open[focusIdx - 1].id);
  };
  const goNext = () => {
    if (focusIdx < open.length - 1) setFocusedId(open[focusIdx + 1].id);
  };

  return (
    <aside className="fixed top-0 right-0 h-full w-[420px] bg-[var(--surface)] border-l border-[var(--subtle-border)] shadow-2xl z-50 flex flex-col">
      <header className="flex items-center justify-between px-4 py-3 border-b border-[var(--subtle-border)]">
        <div className="min-w-0 flex-1 mr-2">
          <div className="text-[10px] uppercase tracking-wider text-[var(--text-faint)] font-medium">
            Clarification
          </div>
          <div
            className="text-[13px] font-medium text-[var(--text)] truncate"
            title={focused?.scope_ref}
          >
            {focused ? `${focused.kind} · ${focused.scope_ref}` : 'No pending requests'}
          </div>
          {open.length > 1 && (
            <div className="text-[11px] text-[var(--muted)]">
              {focusIdx + 1} of {open.length}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            type="button"
            className="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--muted)] hover:text-[var(--text)] disabled:opacity-30 disabled:hover:bg-transparent"
            disabled={focusIdx <= 0}
            onClick={goPrev}
            aria-label="Previous"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            type="button"
            className="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--muted)] hover:text-[var(--text)] disabled:opacity-30 disabled:hover:bg-transparent"
            disabled={focusIdx >= open.length - 1}
            onClick={goNext}
            aria-label="Next"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            type="button"
            className="p-1 rounded hover:bg-[var(--hover-bg)] text-[var(--muted)] hover:text-[var(--text)]"
            onClick={closePopup}
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
            <div
              className={`inline-block px-3 py-2 rounded-lg text-[13px] max-w-[85%] whitespace-pre-wrap break-words ${
                m.role === 'user'
                  ? 'bg-[var(--accent)] text-white'
                  : 'bg-[var(--overlay-bg)] text-[var(--text)] border border-[var(--subtle-border)]'
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {sending && (
          <div className="text-[11px] text-[var(--muted)] italic">thinking…</div>
        )}
      </div>

      <footer className="border-t border-[var(--subtle-border)] p-3">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Type your answer…"
            className="flex-1 px-3 py-2 rounded-md bg-[var(--overlay-bg)] border border-[var(--subtle-border)] text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] outline-none focus:border-[var(--border-medium)]"
            disabled={!focused || sending}
          />
          <button
            type="button"
            onClick={send}
            disabled={!focused || sending || !input.trim()}
            className="px-3 py-2 rounded-md bg-[var(--accent)] text-white disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90"
            aria-label="Send"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </footer>
    </aside>
  );
}
