'use client';

import type { PendingConfirmation } from '@/hooks/useStreamingChat';

interface ToolConfirmationProps {
  confirmation: PendingConfirmation;
  onConfirm: () => void;
  onDeny: () => void;
  isLoading?: boolean;
}

const TOOL_DESCRIPTIONS: Record<string, string> = {
  create_change_plan:
    'Create a change plan with file patches that can later be applied as a GitHub PR.',
  apply_change_plan:
    'Apply the change plan by creating a GitHub Pull Request with the proposed changes.',
};

export function ToolConfirmation({
  confirmation,
  onConfirm,
  onDeny,
  isLoading = false,
}: ToolConfirmationProps) {
  const description =
    TOOL_DESCRIPTIONS[confirmation.toolName] || confirmation.description;

  return (
    <div
      style={{
        border: '1px solid rgba(245, 158, 11, 0.3)',
        background: 'rgba(245, 158, 11, 0.05)',
        borderRadius: '12px',
        padding: '16px',
        margin: '8px 0',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#f59e0b"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        <span style={{ fontSize: '13px', fontWeight: 600, color: '#f59e0b' }}>
          Action Requires Confirmation
        </span>
      </div>

      <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
        {description}
      </p>

      {confirmation.arguments && Object.keys(confirmation.arguments).length > 0 && (
        <div
          style={{
            fontSize: '11px',
            color: 'var(--muted)',
            background: 'var(--overlay-bg)',
            borderRadius: '6px',
            padding: '8px',
            marginBottom: '12px',
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            maxHeight: '120px',
            overflow: 'auto',
          }}
        >
          <strong>{confirmation.toolName}</strong>
          {'\n'}
          {JSON.stringify(confirmation.arguments, null, 2)}
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px' }}>
        <button
          onClick={onConfirm}
          disabled={isLoading}
          style={{
            background: 'rgba(16, 185, 129, 0.8)',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            padding: '6px 14px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: isLoading ? 'not-allowed' : 'pointer',
            opacity: isLoading ? 0.6 : 1,
          }}
        >
          {isLoading ? 'Executing...' : 'Approve & Execute'}
        </button>
        <button
          onClick={onDeny}
          disabled={isLoading}
          style={{
            background: 'transparent',
            color: 'var(--text-tertiary)',
            border: '1px solid var(--overlay-strong)',
            borderRadius: '6px',
            padding: '6px 14px',
            fontSize: '12px',
            fontWeight: 500,
            cursor: isLoading ? 'not-allowed' : 'pointer',
          }}
        >
          Deny
        </button>
      </div>
    </div>
  );
}
