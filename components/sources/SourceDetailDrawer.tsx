'use client';

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useRouter } from 'next/navigation';
import {
  X, Activity, KeyRound, Shield, Zap, ExternalLink, AlertTriangle, CheckCircle,
  Clock, Database, Cloud, BarChart3, GitBranch, Cog, Eye, HardDrive, Layers, Server,
  Download, FileText, User, Users, Hash, MessageSquare, StickyNote, Edit3,
} from 'lucide-react';
import { LAYER_COLORS, LAYER_LABELS, getToolById } from '@/components/pipeline/types';
import { ControlPlaneSource, STATUS_CONFIG, EXTRACTION_STATUS_CONFIG, SLA_CONFIG } from './types';
import { CAPABILITY_CONFIG } from './capabilities';

const TOOL_ICONS: Record<string, typeof Database> = {
  bigquery: Database, snowflake: Database, postgres: Database, redshift: Database,
  sqlserver: Database, azure_sql: Database, azure_synapse: Database, databricks: Database, mysql: Database,
  fivetran: Cloud, airbyte: Cloud, stitch: Cloud,
  dbt_cloud: GitBranch, dbt_core: GitBranch,
  airflow: Cog, dagster: Cog, prefect: Cog, n8n: Cog,
  looker: BarChart3, tableau: BarChart3, powerbi: BarChart3, metabase: BarChart3,
  elementary: Eye, monte_carlo: Eye, bigeye: Eye, soda: Eye,
  amazon_s3: HardDrive, gcs: HardDrive, adls: HardDrive,
  github: Server,
};

type DrawerTab = 'health' | 'extraction' | 'contract';

function formatDate(iso: string | null): string {
  if (!iso) return 'N/A';
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function formatExpiryDays(iso: string): string {
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  if (days <= 0) return 'Expired';
  if (days === 1) return 'Expires in 1 day';
  return `Expires in ${days} days`;
}

function formatMinutes(mins: number | null): string {
  if (mins === null) return 'Not set';
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.round(mins / 60)}h`;
  return `${Math.round(mins / 1440)}d`;
}

function Section({ title, icon: Icon, children }: { title: string; icon: typeof Activity; children: React.ReactNode }) {
  return (
    <div className="border-t border-[var(--subtle-border)] pt-4 pb-2">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-3.5 h-3.5 text-[var(--text-tertiary)]" />
        <span className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wide">{title}</span>
      </div>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-[var(--text-tertiary)]">{label}</span>
      <div className="text-xs text-[var(--text-secondary)] text-right">{children}</div>
    </div>
  );
}

interface Props {
  source: ControlPlaneSource;
  onClose: () => void;
  onEditContract: (source: ControlPlaneSource) => void;
}

export default function SourceDetailDrawer({ source, onClose, onEditContract }: Props) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<DrawerTab>('health');
  const Icon = TOOL_ICONS[source.toolType] || Layers;
  const tool = getToolById(source.toolType);
  const displayName = tool?.name || source.name;
  const statusCfg = STATUS_CONFIG[source.status];
  const layerColor = LAYER_COLORS[source.layer] || '#6B7280';

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const permissionLevel = (() => {
    const c = source.config;
    if (!c) return 'Unknown';
    if (c.role === 'admin' || c.api_mode === 'admin') return 'Admin';
    if (c.role === 'viewer' || c.api_mode === 'discovery') return 'Read-only';
    if (c.readonly) return 'Read-only';
    return 'Standard';
  })();

  const scopeDetails: { label: string; value: string }[] = [];
  if (source.config) {
    const c = source.config;
    const pairs: [string, string][] = [
      ['Project', c.project_id || c.projectId],
      ['Account', c.account || c.account_name || c.account_id],
      ['Database', c.database || c.dbname],
      ['Schema', c.schema || c.default_dataset || c.dataset || c.datasetId],
      ['Host', c.host || c.base_url || c.server || c.instance_url],
      ['Environment', c.environment || c.env],
      ['Warehouse', c.warehouse],
      ['Group/Workspace', c.group_id || c.workspace_id],
    ];
    for (const [label, val] of pairs) {
      if (val) scopeDetails.push({ label, value: String(val) });
    }
  }

  const tabs: { id: DrawerTab; label: string }[] = [
    { id: 'health', label: 'Health' },
    { id: 'extraction', label: 'Extraction' },
    { id: 'contract', label: 'Contract' },
  ];

  return createPortal(
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div
        className="fixed right-0 top-0 h-full w-full max-w-md bg-[var(--surface)] border-l border-[var(--subtle-border)]
                   z-50 overflow-y-auto shadow-2xl animate-in slide-in-from-right duration-200"
      >
        {/* Header */}
        <div className="sticky top-0 bg-[var(--surface)] border-b border-[var(--subtle-border)] px-5 py-4 z-10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center"
                style={{ backgroundColor: `${layerColor}15` }}
              >
                <Icon className="w-5 h-5" style={{ color: layerColor }} />
              </div>
              <div>
                <div className="text-sm font-semibold text-[var(--text)]">{displayName}</div>
                <div className="text-xs text-[var(--text-faint)]">
                  {LAYER_LABELS[source.layer]} &middot; {source.integrationType}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${statusCfg.bg} ${statusCfg.color}`}>
                <div className={`w-1.5 h-1.5 rounded-full ${statusCfg.color.replace('text-', 'bg-')}`} />
                {statusCfg.label}
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[var(--text-tertiary)] transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex items-center gap-1 mt-3">
            {tabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                  ${activeTab === tab.id
                    ? 'bg-[var(--overlay-medium)] text-[var(--text)]'
                    : 'text-[var(--text-faint)] hover:text-[var(--text-tertiary)]'
                  }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="px-5 py-4 space-y-2">
          {/* ── Health Tab ── */}
          {activeTab === 'health' && (
            <>
              <Section title="Health" icon={Activity}>
                <div className="space-y-2">
                  {source.healthScore !== null && source.healthScore !== undefined && (
                    <Row label="Health Score">
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-1.5 rounded-full bg-[var(--overlay-medium)]">
                          <div
                            className="h-full rounded-full transition-all"
                            style={{
                              width: `${source.healthScore}%`,
                              backgroundColor: source.healthScore >= 80 ? '#10B981' : source.healthScore >= 40 ? '#F59E0B' : '#EF4444',
                            }}
                          />
                        </div>
                        <span className="font-medium w-8 text-right">{source.healthScore}</span>
                      </div>
                    </Row>
                  )}
                  <Row label="Last Checked">{formatDate(source.lastTestedAt)}</Row>
                  <Row label="Last Scan">{formatDate(source.lastScanAt)}</Row>
                  {source.lastError && (
                    <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20">
                      <AlertTriangle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
                      <span className="text-xs text-red-400 break-words">{source.lastError}</span>
                    </div>
                  )}
                  {source.findingsCount > 0 && (
                    <div className="flex items-center gap-3 text-xs">
                      <span className="text-[var(--text-tertiary)]">Findings:</span>
                      <span className="text-[var(--text-secondary)]">{source.findingsCount} total</span>
                      {source.criticalCount > 0 && <span className="text-red-400">{source.criticalCount} critical</span>}
                      {source.highCount > 0 && <span className="text-amber-400">{source.highCount} high</span>}
                    </div>
                  )}
                  {!source.lastError && source.status === 'healthy' && (
                    <div className="flex items-center gap-2 text-xs text-emerald-400">
                      <CheckCircle className="w-3.5 h-3.5" /> All checks passing
                    </div>
                  )}
                </div>
              </Section>

              <Section title="Credentials" icon={KeyRound}>
                <div className="space-y-2">
                  <Row label="Token Expiry">
                    {source.tokenExpiry ? (
                      <span className={`font-medium ${
                        (() => {
                          const days = Math.ceil((new Date(source.tokenExpiry).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
                          if (days <= 0) return 'text-red-400';
                          if (days <= 7) return 'text-yellow-400';
                          return '';
                        })()
                      }`}>
                        {formatExpiryDays(source.tokenExpiry)}
                      </span>
                    ) : (
                      <span className="text-[var(--text-faint)]">No expiry set</span>
                    )}
                  </Row>
                  <Row label="Created">{formatDate(source.createdAt)}</Row>
                  <Row label="Last Updated">{formatDate(source.updatedAt)}</Row>
                </div>
              </Section>

              <Section title="Permissions & Scope" icon={Shield}>
                <div className="space-y-2">
                  <Row label="Access Level"><span className="font-medium">{permissionLevel}</span></Row>
                  {scopeDetails.map(({ label, value }) => (
                    <Row key={label} label={label}>
                      <span className="font-mono truncate max-w-[60%] inline-block text-right">{value}</span>
                    </Row>
                  ))}
                  {scopeDetails.length === 0 && (
                    <div className="text-xs text-[var(--text-faint)]">No scope details available</div>
                  )}
                </div>
              </Section>

              <Section title="Capabilities" icon={Zap}>
                <div className="flex flex-wrap gap-1.5">
                  {source.capabilities.map((cap) => {
                    const cfg = CAPABILITY_CONFIG[cap];
                    return (
                      <span key={cap} className={`px-2 py-1 rounded-md text-xs font-medium ${cfg.bg} ${cfg.color}`}>
                        {cfg.label}
                      </span>
                    );
                  })}
                </div>
              </Section>
            </>
          )}

          {/* ── Extraction Tab ── */}
          {activeTab === 'extraction' && (
            <>
              <Section title="Extraction Status" icon={Download}>
                <div className="space-y-3">
                  {/* Overall status */}
                  <div className="flex items-center gap-2">
                    {(() => {
                      const cfg = EXTRACTION_STATUS_CONFIG[source.extractionStatus];
                      return (
                        <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${cfg.bg} ${cfg.color}`}>
                          {cfg.label}
                        </span>
                      );
                    })()}
                    {source.extractionStatus === 'stale' && source.contract?.expectedExtractionFrequencyMinutes && (
                      <span className="text-xs text-amber-400">
                        Expected every {formatMinutes(source.contract.expectedExtractionFrequencyMinutes)}
                      </span>
                    )}
                  </div>

                  {/* Stale explanation */}
                  {source.extractionStatus === 'stale' && source.lastExtractedAt && source.contract?.expectedExtractionFrequencyMinutes && (
                    <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/20">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />
                      <span className="text-xs text-amber-400">
                        Last extracted {formatDate(source.lastExtractedAt)}, which is more than the expected{' '}
                        {formatMinutes(source.contract.expectedExtractionFrequencyMinutes)} frequency.
                      </span>
                    </div>
                  )}

                  {/* Timestamps */}
                  <div className="space-y-2">
                    <Row label="Last Extracted (Overall)">{formatDate(source.lastExtractedAt)}</Row>
                    <Row label="Last Schema Extracted">{formatDate(source.lastSchemaExtractedAt)}</Row>
                    <Row label="Last Lineage Extracted">{formatDate(source.lastLineageExtractedAt)}</Row>
                    <Row label="Last Logs Extracted">{formatDate(source.lastLogsExtractedAt)}</Row>
                  </div>
                </div>
              </Section>

              <Section title="Freshness Expectations" icon={Clock}>
                <div className="space-y-2">
                  <Row label="Expected Freshness">
                    {formatMinutes(source.contract?.expectedFreshnessMinutes ?? null)}
                  </Row>
                  <Row label="Expected Extraction Frequency">
                    {formatMinutes(source.contract?.expectedExtractionFrequencyMinutes ?? null)}
                  </Row>
                  {!source.contract?.expectedFreshnessMinutes && !source.contract?.expectedExtractionFrequencyMinutes && (
                    <div className="text-xs text-[var(--text-faint)]">
                      No expectations configured.{' '}
                      <button
                        onClick={() => onEditContract(source)}
                        className="text-[var(--accent-2)] hover:underline"
                      >
                        Set expectations
                      </button>
                    </div>
                  )}
                </div>
              </Section>
            </>
          )}

          {/* ── Contract Tab ── */}
          {activeTab === 'contract' && (
            <>
              <Section title="Ownership" icon={Users}>
                <div className="space-y-2">
                  <Row label="Owner (User)">
                    {source.contract?.ownerUser || <span className="text-[var(--text-faint)]">Not set</span>}
                  </Row>
                  <Row label="Owner (Team)">
                    {source.contract?.ownerTeam || <span className="text-[var(--text-faint)]">Not set</span>}
                  </Row>
                  <Row label="Contact Channel">
                    {source.contract?.contactChannel || <span className="text-[var(--text-faint)]">Not set</span>}
                  </Row>
                </div>
              </Section>

              <Section title="SLA" icon={Shield}>
                <div className="space-y-2">
                  <Row label="SLA Tier">
                    {source.contract?.slaTier ? (
                      (() => {
                        const cfg = SLA_CONFIG[source.contract.slaTier];
                        return <span className={`font-medium ${cfg.color}`}>{cfg.label}</span>;
                      })()
                    ) : (
                      <span className="text-[var(--text-faint)]">Not set</span>
                    )}
                  </Row>
                  <Row label="Expected Freshness">
                    {formatMinutes(source.contract?.expectedFreshnessMinutes ?? null)}
                  </Row>
                  <Row label="Extraction Frequency">
                    {formatMinutes(source.contract?.expectedExtractionFrequencyMinutes ?? null)}
                  </Row>
                </div>
              </Section>

              {source.contract?.notes && (
                <Section title="Notes" icon={StickyNote}>
                  <p className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap">{source.contract.notes}</p>
                </Section>
              )}

              <div className="pt-3">
                <button
                  onClick={() => onEditContract(source)}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg border border-[var(--subtle-border)]
                             hover:bg-[var(--hover-bg)] text-sm text-[var(--text-secondary)] transition-colors"
                >
                  <Edit3 className="w-3.5 h-3.5" />
                  Edit Contract
                </button>
              </div>
            </>
          )}

          {/* View in Lineage (always visible) */}
          <div className="pt-4">
            <button
              onClick={() => router.push(`/dashboard/lineage?integrationId=${source.id}`)}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg
                         bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-sm font-medium
                         transition-colors"
            >
              <ExternalLink className="w-4 h-4" />
              View in Lineage
            </button>
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}
