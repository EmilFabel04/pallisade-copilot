'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { CardItem, ItemList, GroupedItemList, EmptyState } from './SharedDetailComponents';

export function IngestionDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  if (tabKey === 'connectors') {
    return <ConnectorsTab items={items} />;
  }
  if (tabKey === 'destinations') {
    return <DestinationsTab items={items} />;
  }
  return <ItemList items={items} />;
}

function ConnectorsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No connectors discovered" hint="Run lineage extraction to discover connectors" />;
  }
  return (
    <div className="space-y-2">
      {items.map(item => {
        const syncedTables = (item.metadata?.synced_tables as string[]) || [];
        const destSchema = item.metadata?.dest_schema || '';
        return (
          <CardItem key={item.id} item={item}>
            <div className="space-y-1 mt-1">
              {destSchema && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Dest</span>
                  <span className="text-[11px] text-[var(--text)] font-mono">{destSchema}</span>
                </div>
              )}
              {syncedTables.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Tables</span>
                  <span className="text-[11px] text-[var(--text)]">{syncedTables.length} synced</span>
                </div>
              )}
            </div>
          </CardItem>
        );
      })}
    </div>
  );
}

function DestinationsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No destination tables discovered" hint="Destination tables appear after sync extraction" />;
  }
  return (
    <GroupedItemList
      items={items}
      groupKey="container"
      labelFn={(item) => item.originalType || item.canonicalType}
    />
  );
}
