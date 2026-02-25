'use client';

import { useState, useEffect } from 'react';
import type { ChangePlan } from '@/types/change-plan';

interface ShareableIntegration {
  id: string;
  name: string;
  type: 'slack' | 'jira' | 'github';
  connectionInfo?: string;
  config?: {
    channel?: string;
    project_key?: string;
    default_repo?: string;
  };
}

interface SharePlanModalProps {
  plan: ChangePlan;
  targetType: 'slack' | 'jira' | 'github_issue';
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (result: { url?: string; message: string }) => void;
}

const TARGET_CONFIG = {
  slack: {
    label: 'Slack',
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z" />
      </svg>
    ),
    color: '#4A154B',
    configLabel: 'Channel',
    configPlaceholder: '#general',
    configKey: 'channel' as const,
  },
  jira: {
    label: 'Jira',
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24 12.483V1.005A1.005 1.005 0 0 0 23.013 0z" />
      </svg>
    ),
    color: '#0052CC',
    configLabel: 'Project Key',
    configPlaceholder: 'PROJ',
    configKey: 'projectKey' as const,
  },
  github_issue: {
    label: 'GitHub Issue',
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
      </svg>
    ),
    color: '#24292e',
    configLabel: 'Repository',
    configPlaceholder: 'owner/repo',
    configKey: 'repository' as const,
  },
};

export function SharePlanModal({ plan, targetType, isOpen, onClose, onSuccess }: SharePlanModalProps) {
  const [integrations, setIntegrations] = useState<ShareableIntegration[]>([]);
  const [selectedIntegration, setSelectedIntegration] = useState<string>('');
  const [configValue, setConfigValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [fetchingIntegrations, setFetchingIntegrations] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const targetConfig = TARGET_CONFIG[targetType];
  const integrationType = targetType === 'github_issue' ? 'github' : targetType;

  // Fetch available integrations
  useEffect(() => {
    if (!isOpen) return;

    const fetchIntegrations = async () => {
      setFetchingIntegrations(true);
      setError(null);

      try {
        const response = await fetch('/api/copilot/share-plan');
        if (!response.ok) throw new Error('Failed to fetch integrations');

        const data = await response.json();
        const filtered = data.integrations.filter(
          (int: ShareableIntegration) => int.type === integrationType
        );
        setIntegrations(filtered);

        // Auto-select if only one integration
        if (filtered.length === 1) {
          setSelectedIntegration(filtered[0].id);
          // Pre-fill config from integration
          const defaultConfig = filtered[0].config?.[targetConfig.configKey === 'projectKey' ? 'project_key' : targetConfig.configKey];
          if (defaultConfig) setConfigValue(defaultConfig);
        }
      } catch (err: any) {
        setError(err.message);
      } finally {
        setFetchingIntegrations(false);
      }
    };

    fetchIntegrations();
  }, [isOpen, integrationType, targetConfig.configKey]);

  // Update config value when integration changes
  useEffect(() => {
    if (!selectedIntegration) return;

    const integration = integrations.find(i => i.id === selectedIntegration);
    if (integration?.config) {
      const key = targetConfig.configKey === 'projectKey' ? 'project_key' : targetConfig.configKey;
      const defaultValue = integration.config[key as keyof typeof integration.config];
      if (defaultValue) setConfigValue(defaultValue);
    }
  }, [selectedIntegration, integrations, targetConfig.configKey]);

  const handleShare = async () => {
    if (!selectedIntegration) {
      setError('Please select an integration');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/copilot/share-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan,
          target: {
            type: targetType,
            integrationId: selectedIntegration,
            channel: targetType === 'slack' ? configValue : undefined,
            projectKey: targetType === 'jira' ? configValue : undefined,
            repository: targetType === 'github_issue' ? configValue : undefined,
          },
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to share plan');
      }

      onSuccess?.({ url: data.url, message: data.message });
      onClose();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div
        className="w-full max-w-md rounded-xl overflow-hidden"
        style={{
          backgroundColor: 'var(--surface)',
          border: '1px solid var(--border-medium)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: '1px solid var(--subtle-border)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: `${targetConfig.color}20`, color: targetConfig.color }}
            >
              {targetConfig.icon}
            </div>
            <div>
              <h2 className="text-sm font-medium text-[var(--text-secondary)]">Share to {targetConfig.label}</h2>
              <p className="text-xs text-[var(--muted)]">{plan.title}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--hover-bg)] transition-colors text-[var(--muted)] hover:text-[var(--text-secondary)]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Error message */}
          {error && (
            <div
              className="p-3 rounded-lg text-sm"
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                color: '#f87171',
              }}
            >
              {error}
            </div>
          )}

          {/* Loading state */}
          {fetchingIntegrations ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin w-6 h-6 border-2 border-[var(--text-faint)] border-t-[var(--text-tertiary)] rounded-full" />
            </div>
          ) : integrations.length === 0 ? (
            /* No integrations */
            <div className="text-center py-8">
              <div
                className="w-12 h-12 mx-auto mb-3 rounded-full flex items-center justify-center"
                style={{ backgroundColor: 'var(--subtle-bg)' }}
              >
                {targetConfig.icon}
              </div>
              <p className="text-sm text-[var(--text-tertiary)] mb-2">No {targetConfig.label} integrations connected</p>
              <a
                href="/dashboard/pipeline"
                className="text-xs text-blue-400 hover:underline"
              >
                Connect {targetConfig.label} in Settings
              </a>
            </div>
          ) : (
            <>
              {/* Integration selector */}
              <div>
                <label className="block text-xs text-[var(--muted)] mb-1.5">
                  Select {targetConfig.label} Integration
                </label>
                <select
                  value={selectedIntegration}
                  onChange={(e) => setSelectedIntegration(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm text-[var(--text-secondary)] outline-none transition-colors"
                  style={{
                    backgroundColor: 'var(--subtle-bg)',
                    border: '1px solid var(--border-medium)',
                  }}
                >
                  <option value="">Select an integration...</option>
                  {integrations.map((int) => (
                    <option key={int.id} value={int.id}>
                      {int.name} {int.connectionInfo ? `(${int.connectionInfo})` : ''}
                    </option>
                  ))}
                </select>
              </div>

              {/* Config input (channel/project/repo) */}
              <div>
                <label className="block text-xs text-[var(--muted)] mb-1.5">
                  {targetConfig.configLabel} {targetType !== 'slack' && <span className="text-red-400">*</span>}
                </label>
                <input
                  type="text"
                  value={configValue}
                  onChange={(e) => setConfigValue(e.target.value)}
                  placeholder={targetConfig.configPlaceholder}
                  className="w-full px-3 py-2 rounded-lg text-sm text-[var(--text-secondary)] placeholder:text-[var(--text-faint)] outline-none transition-colors"
                  style={{
                    backgroundColor: 'var(--subtle-bg)',
                    border: '1px solid var(--border-medium)',
                  }}
                />
                {targetType === 'slack' && (
                  <p className="text-xs text-[var(--muted)] mt-1">Leave empty for default channel</p>
                )}
              </div>

              {/* Preview */}
              <div>
                <label className="block text-xs text-[var(--muted)] mb-1.5">Preview</label>
                <div
                  className="p-3 rounded-lg text-xs space-y-1"
                  style={{
                    backgroundColor: 'var(--overlay-faint)',
                    border: '1px solid var(--subtle-border)',
                  }}
                >
                  <div className="font-medium text-[var(--text-secondary)]">
                    {targetType === 'jira' ? `[Scout] ${plan.title}` : `Change Plan: ${plan.title}`}
                  </div>
                  <div className="text-[var(--muted)] line-clamp-2">
                    {plan.description || plan.root_cause || 'A change plan has been created.'}
                  </div>
                  <div className="flex gap-2 pt-1 text-[var(--muted)]">
                    <span>{plan.patches.length} files</span>
                    <span>|</span>
                    <span>{plan.impact_analysis?.risk_level || 'LOW'} risk</span>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        {integrations.length > 0 && !fetchingIntegrations && (
          <div
            className="flex items-center justify-end gap-2 px-4 py-3"
            style={{ borderTop: '1px solid var(--subtle-border)' }}
          >
            <button
              onClick={onClose}
              disabled={loading}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--hover-bg)] transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleShare}
              disabled={loading || !selectedIntegration || (targetType !== 'slack' && !configValue)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
              style={{
                backgroundColor: `${targetConfig.color}30`,
                color: targetConfig.color === '#24292e' ? '#fff' : targetConfig.color,
                border: `1px solid ${targetConfig.color}50`,
              }}
            >
              {loading ? (
                <>
                  <div className="animate-spin w-3 h-3 border-2 border-current border-t-transparent rounded-full" />
                  Sharing...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"
                    />
                  </svg>
                  Share
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
