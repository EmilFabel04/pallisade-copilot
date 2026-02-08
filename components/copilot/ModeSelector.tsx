'use client';

import { useState, useRef, useEffect } from 'react';

export type Mode = {
  id: string;
  name: string;
  description: string;
  icon: string;
  color: string;
};

export const MODES: Mode[] = [
  { id: 'ask', name: 'Ask', description: 'General questions', icon: 'question', color: 'blue' },
  { id: 'debug', name: 'Debug', description: 'Failure analysis', icon: 'bug', color: 'red' },
  { id: 'plan', name: 'Plan', description: 'Strategic changes', icon: 'map', color: 'purple' },
  { id: 'create', name: 'Create', description: 'Generate artifacts', icon: 'sparkles', color: 'green' },
  { id: 'bundle', name: 'Bundle', description: 'Package deliverables', icon: 'package', color: 'orange' },
  { id: 'explain', name: 'Explain', description: 'Deep understanding', icon: 'book-open', color: 'cyan' },
  { id: 'suggest', name: 'Suggest', description: 'Improvements', icon: 'lightbulb', color: 'yellow' },
];

// Using CSS variables and rgba for colors to avoid Tailwind purge issues
const MODE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  blue: { bg: 'rgba(59, 130, 246, 0.2)', text: '#60a5fa', border: 'rgba(59, 130, 246, 0.3)' },
  red: { bg: 'rgba(239, 68, 68, 0.2)', text: '#f87171', border: 'rgba(239, 68, 68, 0.3)' },
  purple: { bg: 'rgba(168, 85, 247, 0.2)', text: '#c084fc', border: 'rgba(168, 85, 247, 0.3)' },
  green: { bg: 'rgba(16, 185, 129, 0.2)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' },
  orange: { bg: 'rgba(249, 115, 22, 0.2)', text: '#fb923c', border: 'rgba(249, 115, 22, 0.3)' },
  cyan: { bg: 'rgba(6, 182, 212, 0.2)', text: '#22d3ee', border: 'rgba(6, 182, 212, 0.3)' },
  yellow: { bg: 'rgba(234, 179, 8, 0.2)', text: '#fbbf24', border: 'rgba(234, 179, 8, 0.3)' },
};

const MODE_ICONS: Record<string, React.ReactNode> = {
  question: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
  bug: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 12.75c1.148 0 2.278.08 3.383.237 1.037.146 1.866.966 1.866 2.013 0 3.728-2.35 6.75-5.25 6.75S6.75 18.728 6.75 15c0-1.046.83-1.867 1.866-2.013A24.204 24.204 0 0112 12.75zm0 0c2.883 0 5.647.508 8.207 1.44a23.91 23.91 0 01-1.152-6.135c-.022-.824.192-1.64.573-2.37a2.25 2.25 0 00-.163-2.36A7.492 7.492 0 0012 2.25a7.493 7.493 0 00-7.464 1.074 2.25 2.25 0 00-.164 2.36c.381.73.595 1.546.573 2.37a23.906 23.906 0 01-1.152 6.135A23.97 23.97 0 0112 12.75z" />
    </svg>
  ),
  map: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z" />
    </svg>
  ),
  sparkles: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
    </svg>
  ),
  package: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
    </svg>
  ),
  'book-open': (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
    </svg>
  ),
  lightbulb: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
    </svg>
  ),
};

interface ModeSelectorProps {
  selected: string;
  onSelect: (mode: string) => void;
  compact?: boolean;
}

export function ModeSelector({ selected, onSelect, compact = false }: ModeSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedMode = MODES.find(m => m.id === selected) || MODES[0];
  const colors = MODE_COLORS[selectedMode.color] || MODE_COLORS.blue;

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-all whitespace-nowrap"
        style={{
          backgroundColor: colors.bg,
          color: colors.text,
          border: `1px solid ${colors.border}`,
        }}
      >
        {MODE_ICONS[selectedMode.icon] || <span>?</span>}
        {!compact && <span>{selectedMode.name}</span>}
        <svg className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute left-0 bottom-full mb-2 w-64 bg-[#1a1a24] border border-[rgba(255,255,255,0.1)] rounded-xl shadow-xl z-50 overflow-hidden">
          <div className="p-3 border-b border-[rgba(255,255,255,0.06)]">
            <h4 className="text-sm font-medium">Select Mode</h4>
            <p className="text-xs text-[var(--muted)] mt-0.5">Choose how Scout should respond</p>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {MODES.map((mode) => (
              <button
                key={mode.id}
                onClick={() => {
                  onSelect(mode.id);
                  setIsOpen(false);
                }}
                className={`w-full p-3 text-left hover:bg-[rgba(255,255,255,0.04)] transition-colors flex items-center gap-3 ${
                  selected === mode.id ? 'bg-[rgba(255,255,255,0.06)]' : ''
                }`}
              >
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{
                    backgroundColor: MODE_COLORS[mode.color].bg,
                    color: MODE_COLORS[mode.color].text,
                    border: `1px solid ${MODE_COLORS[mode.color].border}`,
                  }}
                >
                  {MODE_ICONS[mode.icon]}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{mode.name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[rgba(255,255,255,0.08)] text-[var(--muted)]">
                      /{mode.id}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--muted)] mt-0.5 truncate">{mode.description}</p>
                </div>
                {selected === mode.id && (
                  <svg className="w-4 h-4 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function getModeFromSlashCommand(message: string): { mode: string; message: string } | null {
  const commands: Record<string, string> = {
    '/ask': 'ask',
    '/debug': 'debug',
    '/plan': 'plan',
    '/create': 'create',
    '/bundle': 'bundle',
    '/explain': 'explain',
    '/suggest': 'suggest',
  };

  for (const [cmd, mode] of Object.entries(commands)) {
    if (message.toLowerCase().startsWith(cmd)) {
      return {
        mode,
        message: message.slice(cmd.length).trim(),
      };
    }
  }
  return null;
}
