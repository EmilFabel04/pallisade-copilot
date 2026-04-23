'use client';

import { useState, useRef, useEffect } from 'react';
import { MoreVertical, Eye, Pencil, Trash2, Archive, Power } from 'lucide-react';

export type SLAStatus = 'active' | 'inactive' | 'archived';

interface SLACardMenuProps {
  status: SLAStatus;
  onView: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onArchive: () => void;
  onToggleActive: () => void;
}

export function SLACardMenu({ status, onView, onEdit, onDelete, onArchive, onToggleActive }: SLACardMenuProps) {
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

  const isArchived = status === 'archived';
  const isActive = status === 'active';

  const items = [
    { icon: Eye, label: 'View', action: onView },
    { icon: Pencil, label: 'Edit', action: onEdit },
    { icon: Power, label: isActive ? 'Set Inactive' : 'Set Active', action: onToggleActive },
    { icon: Archive, label: isArchived ? 'Unarchive' : 'Archive', action: onArchive },
    { icon: Trash2, label: 'Delete', action: onDelete, danger: true },
  ];

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className="p-1 rounded-md hover:bg-[var(--hover-bg)] text-[var(--text-faint)] hover:text-[var(--text)] transition-colors"
      >
        <MoreVertical className="w-4 h-4" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-44 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] shadow-xl z-50 py-1 overflow-hidden">
          {items.map((item) => (
            <button
              key={item.label}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                item.action();
              }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 text-[13px] transition-colors
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
