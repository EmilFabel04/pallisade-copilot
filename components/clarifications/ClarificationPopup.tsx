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
import { BorderlineFailureCard } from './BorderlineFailureCard';
import type { ContextRequest } from '@/lib/clarifications/types';

interface ChatMsg {
  role: 'user' | 'assistant';
  content: string;
}

/**
 * Render the opening question from a ContextRequest payload directly when we
 * know its shape, so the popup never has to wait on an LLM round-trip to show
 * the user what they're being asked. Returns null for kinds we don't recognise
 * — the caller falls back to the LLM-driven chat.
 */
function buildOpeningMessage(req: ContextRequest): string | null {
  if (req.kind === 'timestamp_choice') {
    const payload = req.payload as {
      table_fqn?: string;
      candidates?: string[];
      evidence?: { picked_column?: string };
    };
    const tableShort =
      (payload.table_fqn ?? req.scope_ref ?? '').split('.').slice(-1)[0] ||
      req.scope_ref;
    const picked = payload.evidence?.picked_column;
    const candidates = payload.candidates ?? [];

    const intro = picked
      ? `Which column should Pallisade use to bucket volume monitoring on \`${tableShort}\` — is \`${picked}\` the right one?`
      : `Which column should Pallisade use to bucket volume monitoring on \`${tableShort}\`?`;

    const tail =
      "This is the column I'll use to count rows per day so volume drops/spikes get caught.";

    if (candidates.length > 1) {
      const others = candidates.filter((c) => c !== picked);
      const candidateLine = others.length
        ? `\n\nOther candidates: ${others.map((c) => `\`${c}\``).join(', ')}.`
        : '';
      return `${intro}\n\n${tail}${candidateLine}`;
    }
    return `${intro}\n\n${tail}`;
  }
  return null;
}

export function ClarificationPopup() {
  const { popupOpen, closePopup, requests, focusedId, setFocusedId, refresh } =
    useClarifications();
  // Per-clarification chat history. Each request id owns its own thread so
  // navigating between questions never lets a pending reply land in the wrong
  // chat, and prior context is preserved if the user comes back.
  const [chats, setChats] = useState<Record<string, ChatMsg[]>>({});
  const [inputByChat, setInputByChat] = useState<Record<string, string>>({});
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [loadingQuestionId, setLoadingQuestionId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const open = requests.filter((r) => r.status === 'open');
  const focusIdx = focusedId ? open.findIndex((r) => r.id === focusedId) : 0;
  const focused = open[Math.max(0, focusIdx)] ?? null;
  const focusedKey = focused?.id ?? '';
  const messages = chats[focusedKey] ?? [];
  const input = inputByChat[focusedKey] ?? '';
  const sending = sendingId === focusedKey;
  const loadingQuestion = loadingQuestionId === focusedKey;

  useEffect(() => {
    if (!popupOpen || !focused) return;
    // Already seeded — don't re-fetch when navigating back to a thread.
    if (chats[focused.id] && chats[focused.id].length > 0) return;

    // Fast path: payload-driven question — render immediately, no LLM call.
    const direct = buildOpeningMessage(focused);
    if (direct !== null) {
      setChats((prev) => ({ ...prev, [focused.id]: [{ role: 'assistant', content: direct }] }));
      return;
    }

    // Fallback: kinds we don't render directly fall through to the LLM chat.
    // Track the request id we fired for so a late reply can't land in a
    // different chat after the user navigates away.
    const requestId = focused.id;
    setLoadingQuestionId(requestId);
    fetch('/api/copilot/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: '',
        mode: 'clarify',
        clarification_request_id: requestId,
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        const reply = data?.message ?? data?.reply ?? '...';
        setChats((prev) => ({
          ...prev,
          [requestId]: [{ role: 'assistant', content: reply }],
        }));
      })
      .catch(() => {
        setChats((prev) => ({
          ...prev,
          [requestId]: [{ role: 'assistant', content: '(failed to load question)' }],
        }));
      })
      .finally(() => {
        setLoadingQuestionId((cur) => (cur === requestId ? null : cur));
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
    const requestId = focused.id;
    const userMsg: ChatMsg = { role: 'user', content: input };
    const historyAtSend = [...(chats[requestId] ?? []), userMsg];
    setChats((prev) => ({ ...prev, [requestId]: historyAtSend }));
    setInputByChat((prev) => ({ ...prev, [requestId]: '' }));
    setSendingId(requestId);
    try {
      const res = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMsg.content,
          mode: 'clarify',
          clarification_request_id: requestId,
          history: historyAtSend,
        }),
      });
      const data = await res.json();
      const reply = data?.message ?? data?.reply ?? '(no response)';
      setChats((prev) => ({
        ...prev,
        [requestId]: [...(prev[requestId] ?? historyAtSend), { role: 'assistant', content: reply }],
      }));
      await refresh();
    } catch {
      setChats((prev) => ({
        ...prev,
        [requestId]: [...(prev[requestId] ?? historyAtSend), { role: 'assistant', content: '(failed to send)' }],
      }));
    } finally {
      setSendingId((cur) => (cur === requestId ? null : cur));
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

      {focused?.kind === 'failure_review' && (
        <div className="px-4 pt-3">
          <BorderlineFailureCard
            request={focused}
            onAnswered={() => {
              void refresh();
            }}
          />
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {loadingQuestion && messages.length === 0 && (
          <div className="flex items-center gap-2 text-[11px] text-[var(--muted)]">
            <div className="w-3 h-3 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
            <span>Preparing question…</span>
          </div>
        )}
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
            onChange={(e) =>
              focusedKey &&
              setInputByChat((prev) => ({ ...prev, [focusedKey]: e.target.value }))
            }
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Type your answer…"
            className="flex-1 px-3 py-2 rounded-md bg-[var(--overlay-bg)] border border-[var(--subtle-border)] text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] outline-none focus:border-[var(--border-medium)]"
            disabled={!focused || sending || loadingQuestion}
          />
          <button
            type="button"
            onClick={send}
            disabled={!focused || sending || loadingQuestion || !input.trim()}
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
