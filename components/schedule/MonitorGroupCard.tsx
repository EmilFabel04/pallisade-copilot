'use client';

/**
 * MonitorGroupCard — renamed from WatchCard with updated terminology.
 *
 * Re-exports the existing WatchCard component under the new name.
 * "Watch" → "Monitor Group" in the unified monitoring plan architecture.
 */

export { WatchCard as MonitorGroupCard } from './WatchCard';
export type { default as MonitorGroupCardProps } from './WatchCard';
