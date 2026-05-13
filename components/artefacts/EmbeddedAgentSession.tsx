'use client';

import { useEffect, useRef, useState } from 'react';
import { useStreamingChat } from '@/hooks/useStreamingChat';
import { useArtefactSession, type SessionMessage } from '@/hooks/useArtefactSession';

interface EmbeddedAgentSessionProps {
  agentSessionId: string;
  pipelineStackId?: string;
}

export function EmbeddedAgentSession({ agentSessionId, pipelineStackId }: EmbeddedAgentSessionProps) {
  const { messages, isLoading, error, refresh } = useArtefactSession(agentSessionId);
  const { streamingMessage, sendMessage, abort } = useStreamingChat();

  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (streamingMessage && !streamingMessage.isStreaming && streamingMessage.stopReason === 'end_turn') {
      refresh();
    }
  }, [streamingMessage, refresh]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages.length, streamingMessage?.content]);

  async function handleSend() {
    if (!input.trim() || pending) return;
    setPending(true);
    try {
      await sendMessage(input, {
        sessionId: agentSessionId,
        pipelineStackId,
        model: 'claude-sonnet-4-6',
        mode: 'chat',
      });
      setInput('');
    } finally {
      setPending(false);
    }
  }

  function renderMessage(m: SessionMessage | { role: string; content: string; id: string }) {
    const isUser = m.role === 'user';
    return (
      <div key={m.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
        <div
          className={`max-w-[85%] rounded-2xl px-3 py-2 text-[14px] whitespace-pre-wrap ${
            isUser
              ? 'bg-[var(--hover-bg)] text-[var(--text)]'
              : 'bg-[var(--surface-inset)] text-[var(--text)]'
          }`}
        >
          {m.content}
        </div>
      </div>
    );
  }

  return (
    <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] flex flex-col h-[600px]">
      <div className="px-5 py-3 border-b border-[var(--border)] flex items-center justify-between">
        <h2 className="text-[14px] font-semibold text-[var(--text)]">Agent session</h2>
        <span className="text-[11px] text-[var(--muted)] font-mono">{agentSessionId.slice(0, 8)}</span>
      </div>

      <div ref={listRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {isLoading ? (
          <div className="text-[13px] text-[var(--muted)]">Loading session…</div>
        ) : error ? (
          <div className="text-[13px] text-rose-300">{error}</div>
        ) : messages.length === 0 && !streamingMessage ? (
          <div className="text-[13px] text-[var(--muted)]">
            No messages yet. Send one below to continue this artefact.
          </div>
        ) : (
          messages.map((m) => renderMessage(m))
        )}
        {streamingMessage ? (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-2xl px-3 py-2 text-[14px] whitespace-pre-wrap bg-[var(--surface-inset)] text-[var(--text)]">
              {streamingMessage.content}
              {streamingMessage.isStreaming ? <span className="text-[var(--muted)]"> ▍</span> : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="px-5 py-3 border-t border-[var(--border)]">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Continue this artefact…"
            rows={2}
            className="flex-1 resize-none rounded-md bg-[var(--surface-inset)] border border-[var(--border)] px-3 py-2 text-[14px] text-[var(--text)] focus:outline-none focus:border-[var(--hover-bg)]"
          />
          {streamingMessage?.isStreaming ? (
            <button
              onClick={abort}
              className="px-3 py-2 rounded-md bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 text-[13px]"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={pending || !input.trim()}
              className="px-3 py-2 rounded-md bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-[13px] disabled:opacity-50"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
