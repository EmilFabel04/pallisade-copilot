'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { ItemList } from './SharedDetailComponents';

export function GenericDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  return (
    <ItemList
      items={items}
      labelFn={(item) => item.originalType || item.canonicalType}
    />
  );
}
