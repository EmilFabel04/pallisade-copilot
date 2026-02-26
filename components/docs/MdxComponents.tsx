import type { MDXComponents } from 'mdx/types';
import React from 'react';

function Callout({
  type = 'info',
  children,
}: {
  type?: 'info' | 'warning' | 'tip';
  children: React.ReactNode;
}) {
  const config = {
    info: {
      border: 'var(--accent-2)',
      bg: 'rgba(165, 26, 31, 0.06)',
      label: 'Info',
    },
    warning: {
      border: '#f59e0b',
      bg: 'rgba(245, 158, 11, 0.06)',
      label: 'Warning',
    },
    tip: {
      border: '#10b981',
      bg: 'rgba(16, 185, 129, 0.06)',
      label: 'Tip',
    },
  }[type];

  return (
    <div
      className="my-6 rounded-lg border-l-4 px-5 py-4"
      style={{
        borderLeftColor: config.border,
        backgroundColor: config.bg,
      }}
    >
      <p
        className="mb-1 text-xs font-semibold uppercase tracking-wider"
        style={{ color: config.border }}
      >
        {config.label}
      </p>
      <div className="text-sm text-[var(--text-secondary)]">{children}</div>
    </div>
  );
}

function Steps({ children }: { children: React.ReactNode }) {
  return (
    <div className="my-6 ml-4 border-l-2 border-[var(--border)] pl-6 [counter-reset:step]">
      {children}
    </div>
  );
}

function Step({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="relative mb-8 last:mb-0 [counter-increment:step]">
      <div
        className="absolute -left-[33px] flex h-7 w-7 items-center justify-center rounded-full border-2 border-[var(--accent-2)] bg-[var(--bg)] text-xs font-bold text-[var(--accent-2)] before:content-[counter(step)]"
      />
      <h3 className="mb-2 text-base font-semibold text-[var(--text)]">
        {title}
      </h3>
      <div className="text-sm text-[var(--text-secondary)]">{children}</div>
    </div>
  );
}

export const mdxComponents: MDXComponents = {
  Callout,
  Steps,
  Step,
};
