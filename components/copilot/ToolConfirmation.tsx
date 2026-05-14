'use client';

import { AlertTriangle, Check, X } from 'lucide-react';
import type { PendingConfirmation } from '@/hooks/useStreamingChat';
import { MonitorConfirmationCard } from './artifacts/MonitorConfirmationCard';

interface ToolConfirmationProps {
  confirmation: PendingConfirmation;
  /**
   * Called when the user approves. Pass `editedArguments` to override what
   * the LLM proposed (used by the typed monitor preview to send the user's
   * tweaks back through the existing `pending_tool_call.arguments` wire).
   */
  onConfirm: (editedArguments?: Record<string, any>) => void;
  onDeny: () => void;
  isLoading?: boolean;
}

const TOOL_DESCRIPTIONS: Record<string, string> = {
  create_change_plan:
    'Create a change plan with file patches that can later be applied as a GitHub PR.',
  apply_change_plan:
    'Apply the change plan by creating a GitHub Pull Request with the proposed changes.',
};

const MONITOR_TOOLS = new Set(['create_monitor', 'update_monitor', 'delete_monitor']);

export function ToolConfirmation({
  confirmation,
  onConfirm,
  onDeny,
  isLoading = false,
}: ToolConfirmationProps) {
  // Type-aware preview for monitor write tools — shows a real card with
  // editable name/schedule/config instead of dumping the raw JSON args.
  if (MONITOR_TOOLS.has(confirmation.toolName)) {
    return (
      <MonitorConfirmationCard
        toolName={confirmation.toolName}
        args={confirmation.arguments || {}}
        onConfirm={onConfirm}
        onDeny={onDeny}
        isLoading={isLoading}
      />
    );
  }

  return (
    <GenericToolConfirmation
      confirmation={confirmation}
      onConfirm={() => onConfirm()}
      onDeny={onDeny}
      isLoading={isLoading}
    />
  );
}

// Fallback for tools without a dedicated preview (apply_change_plan, etc.).
// Now uses the same design tokens as the rest of the artefacts UI instead of
// raw inline styles.
function GenericToolConfirmation({
  confirmation,
  onConfirm,
  onDeny,
  isLoading,
}: {
  confirmation: PendingConfirmation;
  onConfirm: () => void;
  onDeny: () => void;
  isLoading: boolean;
}) {
  const description =
    TOOL_DESCRIPTIONS[confirmation.toolName] || confirmation.description;

  return (
    <div className="rounded-xl border border-amber-500/30 bg-[var(--surface)] my-2 overflow-hidden">
      <div className="px-4 pt-4 pb-3 border-b border-[var(--border)]/60">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-2">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold tracking-wider text-amber-200 bg-amber-500/15">
              <AlertTriangle className="h-3 w-3" />
              CONFIRM
            </span>
            <h3 className="text-[14px] font-medium text-[var(--text)] leading-tight">
              {confirmation.toolName}
            </h3>
            {description ? (
              <p className="text-[12.5px] text-[var(--muted)]">{description}</p>
            ) : null}
          </div>

          <button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className="inline-flex items-center gap-1 px-3 py-1 rounded-md text-[12px] font-medium text-emerald-100 bg-emerald-500/20 hover:bg-emerald-500/30 disabled:opacity-50 shrink-0"
          >
            <Check className="h-3 w-3" />
            {isLoading ? 'Executing…' : 'Approve'}
          </button>
        </div>
      </div>

      {confirmation.arguments && Object.keys(confirmation.arguments).length > 0 ? (
        <div className="px-4 py-3 border-b border-[var(--border)]/60">
          <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-1.5">
            Arguments
          </div>
          <pre className="text-[12px] font-mono text-[var(--text)] bg-[var(--surface-inset)] rounded-md px-3 py-2 max-h-[160px] overflow-auto whitespace-pre-wrap">
            {JSON.stringify(confirmation.arguments, null, 2)}
          </pre>
        </div>
      ) : null}

      <div className="px-4 pb-3 pt-2 flex items-center justify-between gap-3">
        <span className="text-[11px] uppercase tracking-wider text-[var(--muted)]">
          Action requires confirmation
        </span>
        <button
          type="button"
          onClick={onDeny}
          disabled={isLoading}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[12px] text-[var(--muted)] hover:text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
        >
          <X className="h-3 w-3" />
          Deny
        </button>
      </div>
    </div>
  );
}
