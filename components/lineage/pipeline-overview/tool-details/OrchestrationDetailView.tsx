'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { CardItem, ItemList, GroupedItemList, EmptyState } from './SharedDetailComponents';

export function OrchestrationDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  if (tabKey === 'dags') {
    return <DagsTab items={items} />;
  }
  if (tabKey === 'tasks') {
    return <TasksTab items={items} />;
  }
  return <ItemList items={items} />;
}

function DagsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No DAGs / flows discovered" hint="Connect your orchestrator to discover pipelines" />;
  }
  return (
    <div className="space-y-2">
      {items.map(item => (
        <CardItem key={item.id} item={item}>
          <div className="flex items-center gap-3 mt-1">
            {item.itemCount !== undefined && item.itemCount > 0 && (
              <span className="text-[11px] text-[var(--muted)]">
                {item.itemCount} task{item.itemCount !== 1 ? 's' : ''}
              </span>
            )}
            {item.observedAt && (
              <span className="text-[11px] text-[var(--muted)]">
                Last seen: {new Date(item.observedAt).toLocaleDateString()}
              </span>
            )}
          </div>
        </CardItem>
      ))}
    </div>
  );
}

function TasksTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No tasks discovered" hint="Tasks are extracted from DAG definitions" />;
  }
  return (
    <GroupedItemList
      items={items}
      groupKey="container"
      labelFn={(item) => item.metadata?.operator || item.originalType || 'task'}
    />
  );
}
