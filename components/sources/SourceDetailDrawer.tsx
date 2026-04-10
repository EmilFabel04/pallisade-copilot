'use client';

import { useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useRouter } from 'next/navigation';
import {
  X, Activity, KeyRound, Shield, Zap, ExternalLink, AlertTriangle, CheckCircle,
  Clock, Download, Link2, Plus, Trash2,
} from 'lucide-react';
import { LAYER_COLORS, LAYER_LABELS, getToolById } from '@/components/pipeline/types';
import { ControlPlaneSource, STATUS_CONFIG, EXTRACTION_STATUS_CONFIG, QuickLink } from './types';
import { CAPABILITY_CONFIG } from './capabilities';
import { ToolIcon } from '@/components/icons/ToolIcon';

type DrawerTab = 'health' | 'extraction';

// Layers where data monitors make sense
const MONITORABLE_LAYERS = new Set([
  'INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'ORCHESTRATION',
]);

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

function Section({ title, icon: Icon, children, action }: {
  title: string; icon: typeof Activity; children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="border-t border-[var(--subtle-border)] pt-4 pb-2">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className="w-3.5 h-3.5 text-[var(--text-tertiary)]" />
          <span className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wide">{title}</span>
        </div>
        {action}
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
  onEditSLA?: (source: ControlPlaneSource) => void;
}

export default function SourceDetailDrawer({ source, onClose }: Props) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<DrawerTab>('health');
  const tool = getToolById(source.toolType);
  const displayName = tool?.name || source.name;
  const statusCfg = STATUS_CONFIG[source.status];

  // Quick links state
  const [quickLinks, setQuickLinks] = useState<QuickLink[]>(source.quickLinks || []);
  const [addingLink, setAddingLink] = useState(false);
  const [newLabel, setNewLabel] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Fetch quick links on mount (in case they were updated elsewhere)
  useEffect(() => {
    fetch(`/api/integrations/${source.id}/quick-links`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.quickLinks) setQuickLinks(data.quickLinks); })
      .catch(() => {});
  }, [source.id]);

  const saveLinks = useCallback(async (links: QuickLink[]) => {
    setSaving(true);
    try {
      const res = await fetch(`/api/integrations/${source.id}/quick-links`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quickLinks: links }),
      });
      if (res.ok) setQuickLinks(links);
    } catch {} finally {
      setSaving(false);
    }
  }, [source.id]);

  const handleAddLink = () => {
    if (!newLabel.trim() || !newUrl.trim()) return;
    const updated = [...quickLinks, { label: newLabel.trim(), url: newUrl.trim() }];
    saveLinks(updated);
    setNewLabel('');
    setNewUrl('');
    setAddingLink(false);
  };

  const handleRemoveLink = (index: number) => {
    const updated = quickLinks.filter((_, i) => i !== index);
    saveLinks(updated);
  };

  const permissionLevel = (() => {
    const c = source.config;
    if (!c) return 'Full Access';
    if (c.role === 'admin' || c.api_mode === 'admin') return 'Admin';
    if (c.role === 'viewer' || c.api_mode === 'discovery') return 'Read-only';
    if (c.readonly === true) return 'Read-only';
    if (c.readonly === false) return 'Full Access';
    if (source.status === 'healthy' || source.status === 'degraded') return 'Full Access';
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

  const monitorCount = source.monitorCount ?? 0;
  const monitorPassing = source.monitorPassing ?? 0;
  const monitorFailing = source.monitorFailing ?? 0;
  const monitorWarning = source.monitorWarning ?? 0;
  const supportsMonitors = MONITORABLE_LAYERS.has(source.layer);

  const tabs: { id: DrawerTab; label: string }[] = [
    { id: 'health', label: 'Health' },
    { id: 'extraction', label: 'Extraction' },
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
              <ToolIcon toolType={source.toolType} size={40} />
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
              {/* Monitor Health — only for layers that support monitors */}
              {supportsMonitors && (
                <Section title="Monitor Health" icon={Activity}>
                  <div className="space-y-3">
                    {monitorCount > 0 ? (
                      <>
                        <div className="flex items-center gap-3">
                          <div className="flex-1">
                            <div className="flex items-center justify-between text-xs mb-1.5">
                              <span className="text-[var(--text-tertiary)]">Health</span>
                              <span className={`font-semibold ${
                                monitorFailing > 0 ? 'text-red-400' :
                                monitorWarning > 0 ? 'text-amber-400' : 'text-emerald-400'
                              }`}>
                                {Math.round((monitorPassing / monitorCount) * 100)}%
                              </span>
                            </div>
                            <div className="h-2 bg-[var(--overlay-medium)] rounded-full overflow-hidden flex">
                              {monitorPassing > 0 && (
                                <div className="h-full bg-emerald-400" style={{ width: `${(monitorPassing / monitorCount) * 100}%` }} />
                              )}
                              {monitorWarning > 0 && (
                                <div className="h-full bg-amber-400" style={{ width: `${(monitorWarning / monitorCount) * 100}%` }} />
                              )}
                              {monitorFailing > 0 && (
                                <div className="h-full bg-red-400" style={{ width: `${(monitorFailing / monitorCount) * 100}%` }} />
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-3 text-xs">
                          <div className="flex items-center gap-1.5">
                            <div className="w-2 h-2 rounded-full bg-emerald-400" />
                            <span className="text-[var(--text-secondary)]">{monitorPassing} passing</span>
                          </div>
                          {monitorWarning > 0 && (
                            <div className="flex items-center gap-1.5">
                              <div className="w-2 h-2 rounded-full bg-amber-400" />
                              <span className="text-amber-400">{monitorWarning} warning</span>
                            </div>
                          )}
                          {monitorFailing > 0 && (
                            <div className="flex items-center gap-1.5">
                              <div className="w-2 h-2 rounded-full bg-red-400" />
                              <span className="text-red-400">{monitorFailing} failing</span>
                            </div>
                          )}
                        </div>
                      </>
                    ) : (
                      <div className="px-3 py-3 rounded-md bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
                        <div className="text-xs text-[var(--text-faint)] italic">No monitors configured</div>
                        <div className="text-[10px] text-[var(--text-faint)] mt-1">
                          Create monitors in the lineage view to track health.
                        </div>
                      </div>
                    )}
                  </div>
                </Section>
              )}

              {/* Connection & Findings */}
              <Section title="Connection" icon={Activity}>
                <div className="space-y-2">
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
                      <CheckCircle className="w-3.5 h-3.5" /> Connection healthy
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
              <Section title="Extraction" icon={Download}>
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    {(() => {
                      const cfg = EXTRACTION_STATUS_CONFIG[source.extractionStatus];
                      return (
                        <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${cfg.bg} ${cfg.color}`}>
                          {cfg.label}
                        </span>
                      );
                    })()}
                  </div>
                  <div className="space-y-2">
                    <Row label="Last Extracted">{formatDate(source.lastExtractedAt)}</Row>
                  </div>
                </div>
              </Section>

              <Section title="Tool Info" icon={Clock}>
                <div className="space-y-2">
                  <Row label="Tool Type">
                    <span className="font-medium uppercase">{source.toolType}</span>
                  </Row>
                  <Row label="Integration Type">
                    <span className="font-medium">{source.integrationType}</span>
                  </Row>
                  <Row label="Origin">
                    <span className="font-medium capitalize">{source.origin}</span>
                  </Row>
                  {source.config?.version && (
                    <Row label="Version">
                      <span className="font-mono">{source.config.version}</span>
                    </Row>
                  )}
                  {source.config?.api_version && (
                    <Row label="API Version">
                      <span className="font-mono">{source.config.api_version}</span>
                    </Row>
                  )}
                  {source.config?.environment && (
                    <Row label="Environment">
                      <span className="font-medium">{source.config.environment}</span>
                    </Row>
                  )}
                  {source.config?.region && (
                    <Row label="Region">
                      <span className="font-mono">{source.config.region}</span>
                    </Row>
                  )}
                </div>
              </Section>
            </>
          )}

          {/* ── Quick Links (always visible) ── */}
          <Section
            title="Quick Links"
            icon={Link2}
            action={
              !addingLink ? (
                <button
                  onClick={() => setAddingLink(true)}
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium
                             text-[var(--accent-2)] hover:bg-[var(--overlay-faint)] transition-colors"
                >
                  <Plus className="w-3 h-3" /> Add
                </button>
              ) : null
            }
          >
            <div className="space-y-2">
              {quickLinks.map((link, i) => (
                <div key={i} className="flex items-center gap-2 group">
                  <a
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 flex-1 min-w-0 px-3 py-2 rounded-md
                               bg-[var(--overlay-faint)] border border-[var(--subtle-border)]
                               hover:border-[var(--border-medium)] hover:bg-[var(--hover-bg)] transition-colors"
                  >
                    <ExternalLink className="w-3 h-3 text-[var(--accent-2)] shrink-0" />
                    <span className="text-xs font-medium text-[var(--text)] truncate">{link.label}</span>
                    <span className="text-[10px] text-[var(--text-faint)] truncate ml-auto">{
                      (() => { try { return new URL(link.url).hostname; } catch { return link.url; } })()
                    }</span>
                  </a>
                  <button
                    onClick={() => handleRemoveLink(i)}
                    className="p-1 rounded hover:bg-red-500/10 text-[var(--text-faint)] hover:text-red-400
                               opacity-0 group-hover:opacity-100 transition-all shrink-0"
                    title="Remove link"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}

              {quickLinks.length === 0 && !addingLink && (
                <div className="text-xs text-[var(--text-faint)] italic">
                  No links added. Add URLs to quickly navigate to this tool.
                </div>
              )}

              {addingLink && (
                <div className="p-3 rounded-md bg-[var(--overlay-faint)] border border-[var(--subtle-border)] space-y-2">
                  <input
                    type="text"
                    placeholder="Label (e.g. Airflow UI)"
                    value={newLabel}
                    onChange={e => setNewLabel(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-md text-xs bg-[var(--surface)] border border-[var(--border-medium)]
                               text-[var(--text)] placeholder:text-[var(--text-faint)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
                    autoFocus
                    onKeyDown={e => { if (e.key === 'Escape') { setAddingLink(false); setNewLabel(''); setNewUrl(''); } }}
                  />
                  <input
                    type="url"
                    placeholder="URL (e.g. https://airflow.example.com)"
                    value={newUrl}
                    onChange={e => setNewUrl(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-md text-xs bg-[var(--surface)] border border-[var(--border-medium)]
                               text-[var(--text)] placeholder:text-[var(--text-faint)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
                    onKeyDown={e => { if (e.key === 'Enter') handleAddLink(); if (e.key === 'Escape') { setAddingLink(false); setNewLabel(''); setNewUrl(''); } }}
                  />
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleAddLink}
                      disabled={!newLabel.trim() || !newUrl.trim() || saving}
                      className="px-3 py-1.5 rounded-md text-xs font-medium bg-[var(--accent)] text-white
                                 hover:bg-[var(--accent-2)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      {saving ? 'Saving...' : 'Save'}
                    </button>
                    <button
                      onClick={() => { setAddingLink(false); setNewLabel(''); setNewUrl(''); }}
                      className="px-3 py-1.5 rounded-md text-xs font-medium text-[var(--text-tertiary)]
                                 hover:bg-[var(--overlay-faint)] transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </Section>

          {/* View in Lineage */}
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
