'use client';

import { cn } from '@/lib/utils';
import { SCHEDULE_PRESETS } from '@/types/schedule';

interface ScheduleInputProps {
  value: string;
  onChange: (value: string) => void;
}

function cronToHuman(cron: string): string {
  const presets: Record<string, string> = {
    '0 * * * *': 'Runs every hour at minute 0',
    '0 */6 * * *': 'Runs every 6 hours',
    '0 8 * * *': 'Runs daily at 8:00 AM',
    '0 8 * * 1-5': 'Runs weekdays at 8:00 AM',
    '0 8 * * 1': 'Runs every Monday at 8:00 AM',
  };
  if (presets[cron]) return presets[cron];

  // Basic parsing for custom crons
  const parts = cron.split(' ');
  if (parts.length === 5) {
    return `Cron: ${cron}`;
  }
  return 'Invalid cron expression';
}

export function ScheduleInput({ value, onChange }: ScheduleInputProps) {
  const isPreset = SCHEDULE_PRESETS.some((p) => p.value === value);

  return (
    <div className="space-y-3">
      {/* Preset buttons */}
      <div className="flex flex-wrap gap-2">
        {SCHEDULE_PRESETS.map((preset) => (
          <button
            key={preset.value}
            type="button"
            onClick={() => onChange(preset.value)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors',
              value === preset.value
                ? 'bg-[var(--overlay-strong)] text-[var(--text)] border border-[var(--overlay-strong)]'
                : 'bg-[var(--overlay-bg)] text-[var(--muted)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)] hover:text-[var(--text-tertiary)]'
            )}
          >
            {preset.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => {
            if (isPreset) onChange('');
          }}
          className={cn(
            'px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors',
            !isPreset && value
              ? 'bg-[var(--overlay-strong)] text-[var(--text)] border border-[var(--overlay-strong)]'
              : 'bg-[var(--overlay-bg)] text-[var(--muted)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)] hover:text-[var(--text-tertiary)]'
          )}
        >
          Custom
        </button>
      </div>

      {/* Custom input */}
      {(!isPreset || !value) && (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="* * * * * (min hour day month weekday)"
          className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
        />
      )}

      {/* Human-readable preview */}
      {value && (
        <p className="text-[11px] text-[var(--muted)]">{cronToHuman(value)}</p>
      )}
    </div>
  );
}
