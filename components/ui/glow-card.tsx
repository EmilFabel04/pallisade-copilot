'use client';

import * as React from 'react';
import { cn } from '../../lib/utils';

export function GlowCard({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const frame = React.useRef<number | null>(null);
  const target = React.useRef({ rx: 0, ry: 0 });

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    el.style.setProperty('--x', `${x}px`);
    el.style.setProperty('--y', `${y}px`);

    // 3D tilt target values
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const dx = (x - cx) / cx;
    const dy = (y - cy) / cy;
    target.current.ry = dx * 6; // rotateY
    target.current.rx = -dy * 6; // rotateX
    if (frame.current == null) animate();
  }

  function handleMouseLeave() {
    const el = ref.current;
    if (!el) return;
    target.current.rx = 0;
    target.current.ry = 0;
    if (frame.current == null) animate();
  }

  function animate() {
    const el = ref.current;
    if (!el) return;
    const style = getComputedStyle(el);
    const currentRx = parseFloat(style.getPropertyValue('--rx') || '0');
    const currentRy = parseFloat(style.getPropertyValue('--ry') || '0');
    const nextRx = currentRx + (target.current.rx - currentRx) * 0.12;
    const nextRy = currentRy + (target.current.ry - currentRy) * 0.12;
    el.style.setProperty('--rx', `${nextRx.toFixed(3)}deg`);
    el.style.setProperty('--ry', `${nextRy.toFixed(3)}deg`);
    frame.current = requestAnimationFrame(animate);
  }

  return (
    <div
      ref={ref}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      className={cn(
        'relative overflow-hidden rounded-2xl border border-[color:var(--border)] bg-[var(--surface-raised)] transition-all duration-200 hover:shadow-[0_20px_60px_rgba(139,11,16,0.22)] p-6 md:p-7 will-change-transform',
        className
      )}
      style={{
        transform: 'perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateZ(0)'
      }}
      {...props}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
        style={{
          background:
            'radial-gradient(600px circle at var(--x,50%) var(--y,50%), rgba(139,11,16,0.30), transparent 40%)'
        }}
      />
      {/* edge sheen */}
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-px rounded-2xl"
        style={{
          background:
            'conic-gradient(from 0deg at 50% 50%, rgba(139,11,16,0.18), transparent 25%, transparent 75%, rgba(139,11,16,0.18))',
          mask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
          WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
          WebkitMaskComposite: 'xor' as any,
          maskComposite: 'exclude' as any,
          padding: '1px',
          opacity: 0.6
        }}
      />
      <div className="relative">{children}</div>
    </div>
  );
}

