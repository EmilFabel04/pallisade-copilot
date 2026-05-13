import type { ArtifactKind } from '@prisma/client';

export type KindMeta = {
  label: string;
  group: 'pr-flow' | 'monitor' | 'data' | 'orchestration' | 'governance' | 'doc';
  tint: string;
};

export const KIND_META: Record<ArtifactKind, KindMeta> = {
  PR_CHANGE:           { label: 'Pull Request',         group: 'pr-flow',       tint: 'text-emerald-400' },
  DBT_CORE_CHANGE:     { label: 'dbt Change',           group: 'pr-flow',       tint: 'text-orange-400'  },
  DBT_CLOUD_CHANGE:    { label: 'dbt Cloud',            group: 'pr-flow',       tint: 'text-orange-300'  },
  SCHEMA_CHANGE:       { label: 'Schema Change',        group: 'data',          tint: 'text-sky-400'     },
  DAG:                 { label: 'DAG',                  group: 'orchestration', tint: 'text-indigo-400'  },
  INGESTION_CONNECTOR: { label: 'Connector',            group: 'orchestration', tint: 'text-cyan-400'    },
  MONITOR:             { label: 'Monitor',              group: 'monitor',       tint: 'text-violet-400'  },
  WATCH:               { label: 'Watch',                group: 'monitor',       tint: 'text-violet-300'  },
  INCIDENT:            { label: 'Incident',             group: 'governance',    tint: 'text-rose-400'    },
  TICKET:              { label: 'Ticket',               group: 'governance',    tint: 'text-amber-400'   },
  NOTIFICATION_RULE:   { label: 'Notification Rule',    group: 'governance',    tint: 'text-yellow-400'  },
  WAREHOUSE_QUERY:     { label: 'Warehouse Query',      group: 'data',          tint: 'text-blue-400'    },
  BI_ASSET:            { label: 'BI Asset',             group: 'data',          tint: 'text-fuchsia-400' },
  STORAGE_OBJECT:      { label: 'Storage Object',       group: 'data',          tint: 'text-teal-400'    },
  SERVER_ACTION:       { label: 'Server Action',        group: 'orchestration', tint: 'text-slate-300'   },
  DOCUMENT:            { label: 'Document',             group: 'doc',           tint: 'text-zinc-300'    },
};

export const ALL_KINDS = Object.keys(KIND_META) as ArtifactKind[];

export function kindLabel(kind: ArtifactKind): string {
  return KIND_META[kind].label;
}
