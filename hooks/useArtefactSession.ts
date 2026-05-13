'use client';

import { useCallback, useEffect, useState } from 'react';

export interface SessionMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  toolCalls: unknown;
  createdAt: string;
}

export interface UseArtefactSessionResult {
  sessionId: string | null;
  messages: SessionMessage[];
  title: string | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useArtefactSession(sessionId: string | null): UseArtefactSessionResult {
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [title, setTitle] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/copilot/sessions/${sessionId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages((data.session?.messages ?? []) as SessionMessage[]);
      setTitle(data.session?.title ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load session');
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  return { sessionId, messages, title, isLoading, error, refresh: load };
}
