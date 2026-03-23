'use client';

import { useState, useEffect } from 'react';
import { Button } from '../ui/button';

const TIMEZONES = Intl.supportedValuesOf('timeZone');

interface ProfileStepProps {
  initialName: string;
  onComplete: (data: { name: string; timezone: string; role: string }) => void;
  isLoading: boolean;
}

const ROLES = [
  'Data Engineer',
  'Analytics Engineer',
  'Data Analyst',
  'Data Scientist',
  'Engineering Manager',
  'Platform Engineer',
  'Other',
];

export function ProfileStep({ initialName, onComplete, isLoading }: ProfileStepProps) {
  const [name, setName] = useState(initialName);
  const [timezone, setTimezone] = useState('');
  const [tzSearch, setTzSearch] = useState('');
  const [role, setRole] = useState('');

  useEffect(() => {
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    setTimezone(detected);
    setTzSearch(detected);
  }, []);

  const filteredTimezones = TIMEZONES.filter((tz) =>
    tz.toLowerCase().includes(tzSearch.toLowerCase())
  );

  const isValid = name.trim() && timezone && role;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[var(--text)]">Your Profile</h2>
        <p className="text-[var(--muted)] mt-1">Tell us a bit about yourself</p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Display Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            placeholder="Your name"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Timezone
          </label>
          <input
            type="text"
            value={tzSearch}
            onChange={(e) => {
              setTzSearch(e.target.value);
              if (TIMEZONES.includes(e.target.value)) {
                setTimezone(e.target.value);
              }
            }}
            onFocus={() => setTzSearch('')}
            onBlur={() => {
              if (!tzSearch && timezone) setTzSearch(timezone);
            }}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            placeholder="Search timezone..."
          />
          {tzSearch && tzSearch !== timezone && filteredTimezones.length > 0 && (
            <div className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)]">
              {filteredTimezones.slice(0, 10).map((tz) => (
                <button
                  key={tz}
                  type="button"
                  onClick={() => {
                    setTimezone(tz);
                    setTzSearch(tz);
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-[var(--text)] hover:bg-[var(--hover-bg)]"
                >
                  {tz}
                </button>
              ))}
            </div>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Role
          </label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
          >
            <option value="">Select your role</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>

      <Button
        onClick={() => onComplete({ name: name.trim(), timezone, role })}
        disabled={!isValid || isLoading}
        className="w-full"
        size="lg"
      >
        {isLoading ? 'Saving...' : 'Continue'}
      </Button>
    </div>
  );
}
