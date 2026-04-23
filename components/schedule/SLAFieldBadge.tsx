'use client';

interface SLAFieldBadgeProps {
  fieldKey: string;
  currentValue: any;
  policyValue: any;
  profileName?: string;
  isOverridden: boolean;
  isLessStrict: boolean;
  onReset?: () => void;
}

export function SLAFieldBadge({
  fieldKey: _fieldKey,
  currentValue: _currentValue,
  policyValue,
  profileName,
  isOverridden,
  isLessStrict,
  onReset,
}: SLAFieldBadgeProps) {
  if (policyValue === null || policyValue === undefined) return null;

  // State 1: Following policy (not overridden)
  if (!isOverridden) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ background: 'var(--subtle-bg)', color: 'var(--muted)' }}>
        Policy
        {profileName && (
          <span className="opacity-70">· {profileName}</span>
        )}
      </span>
    );
  }

  // State 3: Policy violation (overridden AND less strict)
  if (isLessStrict) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 text-[10px] font-medium">
        Policy violation: {String(policyValue)}
        {onReset && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onReset(); }}
            className="ml-0.5 opacity-70 hover:opacity-100 underline underline-offset-2 transition-opacity"
          >
            reset
          </button>
        )}
      </span>
    );
  }

  // State 2: Override, equal or stricter
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 text-[10px] font-medium">
      Override (policy: {String(policyValue)})
      {onReset && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onReset(); }}
          className="ml-0.5 opacity-70 hover:opacity-100 underline underline-offset-2 transition-opacity"
        >
          reset
        </button>
      )}
    </span>
  );
}
