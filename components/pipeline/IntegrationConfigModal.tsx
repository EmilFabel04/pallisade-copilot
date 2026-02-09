'use client';

/**
 * Integration Configuration Modal
 *
 * Modal for configuring auxiliary integrations (notifications, ticketing, observability)
 * Opens inline on the pipeline page instead of redirecting elsewhere
 * Supports OAuth flow for GitHub
 */

import { useState, useEffect } from 'react';
import { X, Loader2, Check, AlertCircle, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import { IntegrationDefinition, ConfigField, INTEGRATION_COLORS } from './types';
import { encrypt } from '@/lib/crypto';

// Integrations that use OAuth instead of manual config
const OAUTH_INTEGRATIONS = ['github_issues', 'github'];

interface IntegrationConfigModalProps {
  integration: IntegrationDefinition | null;
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

interface GitHubConnectionInfo {
  connected: boolean;
  username?: string;
  repoCount?: number;
  avatar?: string;
}

export function IntegrationConfigModal({
  integration,
  isOpen,
  onClose,
  onSuccess,
}: IntegrationConfigModalProps) {
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [githubInfo, setGithubInfo] = useState<GitHubConnectionInfo | null>(null);
  const [loadingGithub, setLoadingGithub] = useState(false);

  // Check if this is an OAuth-based integration
  const isOAuthIntegration = integration && OAUTH_INTEGRATIONS.includes(integration.id);

  // Reset form when modal opens with new integration
  useEffect(() => {
    if (isOpen && integration) {
      setFormData({});
      setTestResult(null);
      setGithubInfo(null);

      // For GitHub, check if already connected
      if (OAUTH_INTEGRATIONS.includes(integration.id)) {
        checkGitHubConnection();
      }
    }
  }, [isOpen, integration]);

  const checkGitHubConnection = async () => {
    setLoadingGithub(true);
    try {
      const res = await fetch('/api/integrations');
      if (res.ok) {
        const data = await res.json();
        const githubIntegration = data.integrations?.find(
          (i: any) => i.type === 'GITHUB' && i.status === 'ACTIVE'
        );
        if (githubIntegration) {
          setGithubInfo({
            connected: true,
            username: githubIntegration.metadata?.username,
            repoCount: githubIntegration.metadata?.repoCount,
            avatar: githubIntegration.metadata?.avatar,
          });
        } else {
          setGithubInfo({ connected: false });
        }
      }
    } catch (error) {
      console.error('Failed to check GitHub connection:', error);
      setGithubInfo({ connected: false });
    } finally {
      setLoadingGithub(false);
    }
  };

  const handleGitHubConnect = () => {
    // Redirect to GitHub OAuth flow
    window.location.href = '/api/integrations/oauth/github';
  };

  if (!isOpen || !integration) return null;

  const handleInputChange = (fieldName: string, value: string) => {
    setFormData(prev => ({ ...prev, [fieldName]: value }));
    setTestResult(null); // Clear test result when form changes
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);

    try {
      // Encrypt sensitive fields before sending
      const encryptedConfig: Record<string, string> = {};
      for (const field of integration.configFields) {
        const value = formData[field.name] || '';
        if (field.type === 'password' && value) {
          encryptedConfig[field.name] = encrypt(value);
        } else {
          encryptedConfig[field.name] = value;
        }
      }

      const res = await fetch('/api/integrations/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: integration.id.toUpperCase(),
          config: encryptedConfig,
        }),
      });

      const data = await res.json();

      if (res.ok && data.success) {
        setTestResult({ success: true, message: 'Connection successful!' });
      } else {
        setTestResult({ success: false, message: data.error || 'Connection failed' });
      }
    } catch (error) {
      setTestResult({ success: false, message: 'Failed to test connection' });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    // Validate required fields
    const missingFields = integration.configFields
      .filter(f => f.required && !formData[f.name])
      .map(f => f.label);

    if (missingFields.length > 0) {
      toast.error(`Missing required fields: ${missingFields.join(', ')}`);
      return;
    }

    setSaving(true);

    try {
      // Encrypt sensitive fields before sending
      const encryptedConfig: Record<string, string> = {};
      for (const field of integration.configFields) {
        const value = formData[field.name] || '';
        if (field.type === 'password' && value) {
          encryptedConfig[field.name] = encrypt(value);
        } else {
          encryptedConfig[field.name] = value;
        }
      }

      const res = await fetch('/api/integrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: integration.id.toUpperCase(),
          name: integration.name,
          config: encryptedConfig,
        }),
      });

      if (res.ok) {
        toast.success(`${integration.name} connected successfully`);
        onSuccess?.();
        onClose();
      } else {
        const data = await res.json();
        toast.error(data.error || 'Failed to save integration');
      }
    } catch (error) {
      toast.error('Failed to save integration');
    } finally {
      setSaving(false);
    }
  };

  const color = INTEGRATION_COLORS[integration.category];

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="w-full max-w-lg bg-[#13131a] border border-[rgba(255,255,255,0.1)] rounded-2xl shadow-2xl overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div
            className="px-6 py-4 border-b border-[rgba(255,255,255,0.1)]"
            style={{ borderTopColor: color, borderTopWidth: '3px' }}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <IntegrationIcon id={integration.id} />
                <div>
                  <h2 className="text-lg font-semibold text-white">{integration.name}</h2>
                  <p className="text-sm text-[var(--muted)]">{integration.description}</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-2 rounded-lg hover:bg-[rgba(255,255,255,0.05)] transition-colors"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
          </div>

          {/* Content - OAuth or Form */}
          {isOAuthIntegration ? (
            <div className="px-6 py-8">
              {loadingGithub ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
                </div>
              ) : githubInfo?.connected ? (
                // Already connected
                <div className="text-center">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full overflow-hidden bg-[rgba(255,255,255,0.05)]">
                    {githubInfo.avatar ? (
                      <img src={githubInfo.avatar} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <GitHubIcon className="w-8 h-8 text-white" />
                      </div>
                    )}
                  </div>
                  <div className="flex items-center justify-center gap-2 text-emerald-400 mb-2">
                    <Check className="w-5 h-5" />
                    <span className="font-medium">Connected</span>
                  </div>
                  <p className="text-white font-medium">@{githubInfo.username}</p>
                  <p className="text-sm text-gray-400 mt-1">
                    {githubInfo.repoCount} repositories available
                  </p>

                  <div className="mt-6 pt-6 border-t border-[rgba(255,255,255,0.1)]">
                    <button
                      onClick={handleGitHubConnect}
                      className="btn btn-secondary text-sm"
                    >
                      Reconnect with different account
                    </button>
                  </div>
                </div>
              ) : (
                // Not connected - show OAuth button
                <div className="text-center">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-[#24292e] flex items-center justify-center">
                    <GitHubIcon className="w-8 h-8 text-white" />
                  </div>
                  <h3 className="text-lg font-medium text-white mb-2">Connect to GitHub</h3>
                  <p className="text-sm text-gray-400 mb-6">
                    Authorize Pallisade to access your repositories for creating issues and pull requests.
                  </p>

                  <button
                    onClick={handleGitHubConnect}
                    className="inline-flex items-center gap-2 px-6 py-3 bg-[#24292e] hover:bg-[#2d3339] text-white font-medium rounded-lg transition-colors"
                  >
                    <GitHubIcon className="w-5 h-5" />
                    Connect with GitHub
                    <ExternalLink className="w-4 h-4 ml-1 opacity-50" />
                  </button>

                  <p className="text-xs text-gray-500 mt-4">
                    We&apos;ll request access to read your repositories and create issues/PRs.
                  </p>
                </div>
              )}
            </div>
          ) : (
            // Regular form for non-OAuth integrations
            <>
              <div className="px-6 py-5 space-y-4 max-h-[60vh] overflow-y-auto">
                {integration.configFields.map((field) => (
                  <ConfigFieldInput
                    key={field.name}
                    field={field}
                    value={formData[field.name] || ''}
                    onChange={(value) => handleInputChange(field.name, value)}
                  />
                ))}

                {/* Test Result */}
                {testResult && (
                  <div
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${
                      testResult.success
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        : 'bg-red-500/10 text-red-400 border border-red-500/20'
                    }`}
                  >
                    {testResult.success ? (
                      <Check className="w-4 h-4" />
                    ) : (
                      <AlertCircle className="w-4 h-4" />
                    )}
                    {testResult.message}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="px-6 py-4 border-t border-[rgba(255,255,255,0.1)] bg-[rgba(0,0,0,0.2)] flex items-center justify-between">
                <button
                  onClick={handleTestConnection}
                  disabled={testing}
                  className="btn btn-secondary text-sm"
                >
                  {testing ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Testing...
                    </>
                  ) : (
                    'Test Connection'
                  )}
                </button>

                <div className="flex items-center gap-2">
                  <button
                    onClick={onClose}
                    className="btn btn-secondary text-sm"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="btn btn-primary text-sm"
                  >
                    {saving ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Saving...
                      </>
                    ) : (
                      'Save Integration'
                    )}
                  </button>
                </div>
              </div>
            </>
          )}

          {/* Footer for OAuth integrations when connected */}
          {isOAuthIntegration && githubInfo?.connected && (
            <div className="px-6 py-4 border-t border-[rgba(255,255,255,0.1)] bg-[rgba(0,0,0,0.2)] flex justify-end">
              <button
                onClick={onClose}
                className="btn btn-primary text-sm"
              >
                Done
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// GitHub Icon Component
function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
    </svg>
  );
}

// Config Field Input Component
function ConfigFieldInput({
  field,
  value,
  onChange,
}: {
  field: ConfigField;
  value: string;
  onChange: (value: string) => void;
}) {
  const baseInputClass =
    'w-full px-3 py-2.5 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.1)] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] transition-colors';

  return (
    <div>
      <label className="block text-sm font-medium text-white mb-1.5">
        {field.label}
        {field.required && <span className="text-red-400 ml-1">*</span>}
      </label>

      {field.type === 'select' ? (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={baseInputClass}
        >
          <option value="">Select...</option>
          {field.options?.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      ) : field.type === 'textarea' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          rows={3}
          className={baseInputClass}
        />
      ) : (
        <input
          type={field.type === 'password' ? 'password' : 'text'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          className={baseInputClass}
        />
      )}

      {field.helperText && (
        <p className="mt-1 text-xs text-gray-500">{field.helperText}</p>
      )}
    </div>
  );
}

// Integration Icon Component
function IntegrationIcon({ id }: { id: string }) {
  const icons: Record<string, { icon: string; color: string }> = {
    slack: { icon: 'S', color: '#4A154B' },
    teams: { icon: 'T', color: '#6264A7' },
    pagerduty: { icon: 'PD', color: '#06AC38' },
    opsgenie: { icon: 'OG', color: '#2684FF' },
    jira: { icon: 'J', color: '#0052CC' },
    linear: { icon: 'L', color: '#5E6AD2' },
    asana: { icon: 'A', color: '#F06A6A' },
    github_issues: { icon: 'GH', color: '#24292e' },
    monte_carlo: { icon: 'MC', color: '#00D4AA' },
    bigeye: { icon: 'BE', color: '#FF6B35' },
    soda: { icon: 'SD', color: '#00C7B7' },
    elementary: { icon: 'EL', color: '#FF914D' },
  };

  const config = icons[id] || { icon: id.slice(0, 2).toUpperCase(), color: '#6B7280' };

  return (
    <div
      className="w-10 h-10 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
      style={{ backgroundColor: config.color }}
    >
      {config.icon}
    </div>
  );
}
