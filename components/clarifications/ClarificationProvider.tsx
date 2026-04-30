'use client';

/**
 * ClarificationProvider — owns the polling loop for open context requests
 * and the open/close state of the popup chat panel.
 *
 * Re-fetches whenever the selected pipeline changes (pipeline profiles are
 * fully isolated; switching profiles must drop stale clarifications) and
 * polls every 15s while mounted so the bell badge stays roughly in sync
 * with backend-emitted requests.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { usePipeline } from '@/contexts/PipelineContext';
import { listContextRequests } from '@/lib/clarifications/client';
import type { ContextRequest } from '@/lib/clarifications/types';

interface Ctx {
  requests: ContextRequest[];
  refresh: () => Promise<void>;
  popupOpen: boolean;
  openPopup: (focusId?: string) => void;
  closePopup: () => void;
  focusedId: string | null;
  setFocusedId: (id: string | null) => void;
}

const ClarificationCtx = createContext<Ctx | null>(null);

const POLL_MS = 15_000;

export function ClarificationProvider({ children }: { children: React.ReactNode }) {
  const { selectedPipelineId } = usePipeline();
  const [requests, setRequests] = useState<ContextRequest[]>([]);
  const [popupOpen, setPopupOpen] = useState(false);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!selectedPipelineId) {
      setRequests([]);
      return;
    }
    try {
      const items = await listContextRequests(selectedPipelineId);
      setRequests(items);
    } catch {
      // Polling is best-effort — swallow errors so a transient 500 doesn't
      // bubble into a console error every 15 seconds.
    }
  }, [selectedPipelineId]);

  useEffect(() => {
    refresh();
    pollRef.current = setInterval(refresh, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh]);

  const openPopup = useCallback(
    (focusId?: string) => {
      if (focusId) {
        setFocusedId(focusId);
      } else if (!focusedId && requests.length) {
        setFocusedId(requests[0].id);
      }
      setPopupOpen(true);
    },
    [focusedId, requests],
  );

  const closePopup = useCallback(() => setPopupOpen(false), []);

  const value = useMemo<Ctx>(
    () => ({
      requests,
      refresh,
      popupOpen,
      openPopup,
      closePopup,
      focusedId,
      setFocusedId,
    }),
    [requests, refresh, popupOpen, openPopup, closePopup, focusedId],
  );

  return <ClarificationCtx.Provider value={value}>{children}</ClarificationCtx.Provider>;
}

export function useClarifications() {
  const ctx = useContext(ClarificationCtx);
  if (!ctx) {
    throw new Error('useClarifications must be used inside ClarificationProvider');
  }
  return ctx;
}
