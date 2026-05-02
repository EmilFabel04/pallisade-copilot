'use client';

import { useState } from 'react';
import Link from 'next/link';
import { TOOLS, LAYER_LABELS, LAYER_COLORS, PipelineLayer } from '@/components/pipeline/types';
import { ToolIcon } from '@/components/icons/ToolIcon';
import { RequestAccessModal } from '@/components/integrations/RequestAccessModal';

const CONNECT_ROUTES: Partial<Record<string, string>> = {
  custom_source: '/dashboard/integrations/connect/custom-source',
  // future live tiles add their wizard routes here
};

const CATEGORY_ORDER: PipelineLayer[] = [
  'SOURCE',
  'INGESTION',
  'TRANSFORMATION',
  'WAREHOUSE',
  'STORAGE',
  'REPORTING',
  'ORCHESTRATION',
  'VERSION_CONTROL',
  'INFRASTRUCTURE',
];

type ComingSoonId = 'salesforce' | 'shopify' | 'hubspot';

export default function ConnectPage() {
  const [modal, setModal] = useState<{ id: ComingSoonId; name: string } | null>(null);

  if (process.env.NEXT_PUBLIC_FEATURE_SOURCES_CATEGORY !== 'true') {
    return <div className="p-6">Sources category not enabled.</div>;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-semibold mb-6 text-[var(--text-primary)]">
        Connect an integration
      </h1>

      {CATEGORY_ORDER.map((layer) => {
        const tools = TOOLS[layer] ?? [];
        if (tools.length === 0) return null;
        return (
          <section key={layer} className="mb-8">
            <h2
              className="text-xs font-semibold uppercase tracking-widest mb-3"
              style={{ color: LAYER_COLORS[layer] }}
            >
              {LAYER_LABELS[layer]}
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {tools.map((tool) => {
                const status = tool.status ?? 'live';
                const route = CONNECT_ROUTES[tool.id];

                if (status === 'live' && route) {
                  return (
                    <Link
                      key={tool.id}
                      href={route}
                      className="border border-[var(--subtle-border)] rounded-xl p-4 hover:border-slate-400 hover:shadow-sm transition-all flex items-start gap-3 bg-[var(--surface)]"
                    >
                      <ToolIcon toolType={tool.id} size={32} />
                      <div className="min-w-0">
                        <div className="font-medium text-sm text-[var(--text-primary)]">
                          {tool.name}
                        </div>
                        <div className="text-xs text-[var(--text-secondary)] mt-1 line-clamp-2">
                          {tool.description}
                        </div>
                      </div>
                    </Link>
                  );
                }

                return (
                  <button
                    key={tool.id}
                    onClick={() =>
                      setModal({ id: tool.id as ComingSoonId, name: tool.name })
                    }
                    className="border border-[var(--subtle-border)] rounded-xl p-4 opacity-60 hover:opacity-80 transition-all flex items-start gap-3 text-left bg-[var(--surface)] w-full"
                  >
                    <ToolIcon toolType={tool.id} size={32} />
                    <div className="min-w-0">
                      <div className="font-medium text-sm text-[var(--text-primary)]">
                        {tool.name}
                        <span className="ml-1 text-xs font-normal text-[var(--text-secondary)]">
                          — coming soon
                        </span>
                      </div>
                      <div className="text-xs text-[var(--text-secondary)] mt-1 line-clamp-2">
                        {tool.description}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}

      {modal && (
        <RequestAccessModal
          connectorId={modal.id}
          connectorName={modal.name}
          open={true}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
