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
    <div
      className="rounded-xl border bg-[var(--surface)] my-2 overflow-hidden max-w-[640px]"
      style={{ borderColor: 'var(--warning-bg)' }}
    >
      <div className="px-3 pt-3 pb-2.5 border-b border-[var(--border)]/60">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1 space-y-1.5">
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wider"
              style={{ color: 'var(--warning-fg)', backgroundColor: 'var(--warning-bg)' }}
            >
              <AlertTriangle className="h-3 w-3" />
              CONFIRM
            </span>
            <h3 className="text-[14px] font-medium text-[var(--text)] leading-tight">
              {confirmation.toolName}
            </h3>
            {description ? (
              <p className="text-[12px] text-[var(--muted)]">{description}</p>
            ) : null}
          </div>

          <button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11.5px] font-medium disabled:opacity-50 shrink-0"
            style={{ color: 'var(--success-fg)', backgroundColor: 'var(--success-bg)' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--success-bg-strong)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--success-bg)'; }}
          >
            <Check className="h-3 w-3" />
            {isLoading ? 'Executing…' : 'Approve'}
          </button>
        </div>
      </div>

      {confirmation.arguments && Object.keys(confirmation.arguments).length > 0 ? (
        <div className="px-3 py-2.5 border-b border-[var(--border)]/60">
          <div className="text-[10.5px] uppercase tracking-wider text-[var(--muted)] mb-1">
            Arguments
          </div>
          <pre className="text-[11.5px] font-mono text-[var(--text)] bg-[var(--surface-inset)] rounded-md px-2.5 py-1.5 max-h-[140px] overflow-auto whitespace-pre-wrap">
            {JSON.stringify(confirmation.arguments, null, 2)}
          </pre>
        </div>
      ) : null}

      <div className="px-3 pb-2.5 pt-1.5 flex items-center justify-between gap-3">
        <span className="text-[10.5px] uppercase tracking-wider text-[var(--muted)]">
          Action requires confirmation
        </span>
        <button
          type="button"
          onClick={onDeny}
          disabled={isLoading}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11.5px] text-[var(--muted)] hover:bg-[var(--hover-bg)] disabled:opacity-50"
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--danger-fg)'; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--muted)'; }}
        >
          <X className="h-3 w-3" />
          Deny
        </button>
      </div>
    </div>
  );
}
