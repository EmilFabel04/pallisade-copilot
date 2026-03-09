'use client';

import { useState, useRef, useEffect } from 'react';
import { MoreVertical, Wifi, KeyRound, RotateCw, Star, Eye, Unplug, FileText } from 'lucide-react';
import { ControlPlaneSource } from './types';

interface Props {
  source: ControlPlaneSource;
  onTestConnection: (source: ControlPlaneSource) => void;
  onViewDetails: (source: ControlPlaneSource) => void;
  onDisconnect: (source: ControlPlaneSource) => void;
  onEditContract: (source: ControlPlaneSource) => void;
}

export default function SourceActionsMenu({ source, onTestConnection, onViewDetails, onDisconnect, onEditContract }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const items = [
    { icon: Wifi, label: 'Test Connection', action: () => onTestConnection(source) },
    { icon: FileText, label: 'Edit Contract', action: () => onEditContract(source) },
    { icon: KeyRound, label: 'Re-authenticate', action: () => window.open(`/dashboard/pipeline?openConfig=${source.toolType}`, '_self') },
    { icon: RotateCw, label: 'Rotate Key', action: () => window.open(`/dashboard/pipeline?openConfig=${source.toolType}`, '_self') },
    ...(source.layer === 'WAREHOUSE'
      ? [{ icon: Star, label: 'Set as Default', action: () => {} }]
      : []),
    { icon: Eye, label: 'View Details', action: () => onViewDetails(source) },
    { icon: Unplug, label: 'Disconnect', action: () => onDisconnect(source), danger: true },
  ];

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className="p-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[var(--text-tertiary)] hover:text-[var(--text)]
                   transition-colors"
      >
        <MoreVertical className="w-4 h-4" />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-48 rounded-lg border border-[var(--subtle-border)]
                     bg-[var(--surface)] shadow-xl z-50 py-1 overflow-hidden"
        >
          {items.map((item) => (
            <button
              key={item.label}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                item.action();
              }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors
                ${(item as any).danger
                  ? 'text-red-400 hover:bg-red-500/10'
                  : 'text-[var(--text-secondary)] hover:bg-[var(--hover-bg)] hover:text-[var(--text)]'
                }`}
            >
              <item.icon className="w-3.5 h-3.5" />
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
