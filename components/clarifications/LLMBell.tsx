'use client';

/**
 * LLMBell — top-bar trigger that opens the clarification popup chat.
 *
 * Visual style mirrors the existing notification button in
 * `components/dashboard/Header.tsx` (CSS var palette, accent badge) so the
 * two icons look like siblings. The lucide Lightbulb is used per spec; the
 * project does pull in lucide-react via package.json already.
 */

import { Lightbulb } from 'lucide-react';
import { useClarifications } from './ClarificationProvider';

export function LLMBell() {
  const { requests, openPopup } = useClarifications();
  const open = requests.filter((r) => r.status === 'open');
  const count = open.length;
  const critical = open.some((r) => r.priority === 'critical');

  return (
    <button
      type="button"
      onClick={() => openPopup()}
      className="relative p-2 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-colors"
      aria-label={`${count} pending clarifications`}
      title={
        count
          ? `${count} clarification${count === 1 ? '' : 's'} need your input`
          : 'No pending clarifications'
      }
    >
      <Lightbulb
        className={`w-5 h-5 ${count ? 'text-amber-400' : ''}`}
        strokeWidth={1.5}
      />
      {count > 0 && (
        <span
          className={`absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] flex items-center justify-center px-1 rounded-full text-white text-[10px] font-semibold leading-none ${
            critical ? 'bg-red-500 animate-pulse' : 'bg-amber-500'
          }`}
        >
          {count > 9 ? '9+' : count}
        </span>
      )}
    </button>
  );
}
