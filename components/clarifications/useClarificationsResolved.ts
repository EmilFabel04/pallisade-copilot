'use client';

import { useEffect, useRef } from 'react';
import { useClarifications } from './ClarificationProvider';
import { fetchContextRequest } from '@/lib/clarifications/client';

/**
 * Fires `onAllResolved({id: answer})` exactly once when every id in `ids`
 * is in status='answered'. Fetches the answer payload for each id at fire
 * time. Resets on each transition out of all-answered so the same hook can
 * be reused across discovery cycles in the same component instance.
 */
export function useClarificationsResolved(
  ids: string[],
  onAllResolved: (answers: Record<string, unknown>) => void,
) {
  const { requestsById } = useClarifications();
  const firedRef = useRef(false);

  useEffect(() => {
    if (ids.length === 0) {
      firedRef.current = false;
      return;
    }

    const allAnswered = ids.every((id) => requestsById[id]?.status === 'answered');

    if (allAnswered && !firedRef.current) {
      firedRef.current = true;
      (async () => {
        const answers: Record<string, unknown> = {};
        await Promise.all(
          ids.map(async (id) => {
            try {
              const r = await fetchContextRequest(id);
              answers[id] = r.answer;
            } catch {
              answers[id] = null;
            }
          }),
        );
        onAllResolved(answers);
      })();
    } else if (!allAnswered) {
      firedRef.current = false;
    }
  }, [ids, requestsById, onAllResolved]);
}
