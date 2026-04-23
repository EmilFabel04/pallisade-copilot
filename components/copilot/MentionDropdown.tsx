'use client';

import { useRef, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { ToolIcon } from '@/components/icons/ToolIcon';

export type MentionItem = {
  label: string;
  value: string;
  category: 'integration' | 'table' | 'model';
  nodeId: string;
  toolType: string;
  detail?: string;
};

interface MentionDropdownProps {
  items: MentionItem[];
  selectedIndex: number;
  onSelect: (item: MentionItem) => void;
  onClose: () => void;
}

export function MentionDropdown({ items, selectedIndex, onSelect, onClose }: MentionDropdownProps) {
  const dropdownRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef<HTMLDivElement>(null);

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose]);

  // Scroll selected item into view
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  if (items.length === 0) {
    return (
      <div
        ref={dropdownRef}
        className="absolute bottom-full left-0 right-0 mb-2 bg-[var(--surface)] border border-[var(--border-medium)] rounded-lg shadow-xl z-50 p-3"
      >
        <p className="text-xs text-[var(--muted)] text-center">No matching integrations or tables</p>
      </div>
    );
  }

  // Group items
  const integrations = items.filter(i => i.category === 'integration');
  const tablesAndModels = items.filter(i => i.category === 'table' || i.category === 'model');

  // Track global index for selection highlighting
  let globalIndex = 0;

  const renderItem = (item: MentionItem) => {
    const idx = globalIndex++;
    const isSelected = idx === selectedIndex;

    return (
      <div
        key={`${item.value}-${idx}`}
        ref={isSelected ? selectedRef : undefined}
        className={cn(
          'flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors',
          isSelected ? 'bg-[var(--hover-bg)]' : 'hover:bg-[var(--overlay-bg)]'
        )}
        onMouseDown={(e) => {
          e.preventDefault(); // Prevent textarea blur
          onSelect(item);
        }}
      >
        <ToolIcon toolType={item.toolType} size={20} />
        <div className="flex-1 min-w-0">
          <span className="text-xs text-[var(--text-secondary)] truncate">{item.label}</span>
        </div>
        {item.detail && (
          <span className="text-[10px] text-[var(--text-faint)] flex-shrink-0">{item.detail}</span>
        )}
      </div>
    );
  };

  return (
    <div
      ref={dropdownRef}
      className="absolute bottom-full left-0 right-0 mb-2 bg-[var(--surface)] border border-[var(--border-medium)] rounded-lg shadow-xl z-50 max-h-[280px] overflow-y-auto"
    >
      {integrations.length > 0 && (
        <div className="p-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-faint)] px-2.5 py-1">Integrations</p>
          {integrations.map(renderItem)}
        </div>
      )}
      {tablesAndModels.length > 0 && (
        <div className={cn('p-1.5', integrations.length > 0 && 'border-t border-[var(--subtle-border)]')}>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-faint)] px-2.5 py-1">Tables & Models</p>
          {tablesAndModels.map(renderItem)}
        </div>
      )}
    </div>
  );
}
