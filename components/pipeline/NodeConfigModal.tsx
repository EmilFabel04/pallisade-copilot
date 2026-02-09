'use client';

/**
 * Node Configuration Modal
 *
 * Professional modal for configuring node credentials and settings
 * Supports OAuth flow for GitHub
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { PipelineNode, getToolById, LAYER_COLORS, ConfigField } from './types';
import { Loader2, Check, ExternalLink } from 'lucide-react';

// Tools that support OAuth authentication
const OAUTH_TOOLS = ['github'];

interface GitHubConnectionInfo {
  connected: boolean;
  username?: string;
  repoCount?: number;
  avatar?: string;
}

interface NodeConfigModalProps {
  node: PipelineNode;
  stackId?: string; // Needed for API calls to fetch dynamic options
  onSave: (config: Record<string, any>) => void;
  onClose: () => void;
}

// Multi-select field component for selecting multiple datasets/schemas
function MultiSelectField({
  field,
  value = [],
  onChange,
  stackId,
  nodeId,
  toolType,
  config,
}: {
  field: ConfigField;
  value: string[];
  onChange: (value: string[]) => void;
  stackId?: string;
  nodeId?: string;
  toolType?: string;
  config: Record<string, any>;
}) {
  const [options, setOptions] = useState<{ value: string; label: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualInput, setManualInput] = useState('');

  // Fetch dynamic options from API
  const fetchOptions = useCallback(async () => {
    if (!field.dynamicOptions || !field.optionsEndpoint) return;
    if (!stackId || !nodeId) {
      // If no node ID yet, allow manual input
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`/api/pipeline/${stackId}/nodes/${nodeId}/${field.optionsEndpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, toolType }),
      });

      if (res.ok) {
        const data = await res.json();
        const items = data.datasets || data.schemas || data.options || [];
        setOptions(items.map((item: string) => ({ value: item, label: item })));
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Failed to load options');
      }
    } catch (err) {
      setError('Failed to fetch options');
    } finally {
      setLoading(false);
    }
  }, [field.dynamicOptions, field.optionsEndpoint, stackId, nodeId, config]);

  useEffect(() => {
    fetchOptions();
  }, [fetchOptions]);

  const toggleOption = (optValue: string) => {
    if (value.includes(optValue)) {
      onChange(value.filter(v => v !== optValue));
    } else {
      onChange([...value, optValue]);
    }
  };

  const addManualValue = () => {
    const trimmed = manualInput.trim();
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed]);
      setManualInput('');
    }
  };

  const removeValue = (v: string) => {
    onChange(value.filter(val => val !== v));
  };

  return (
    <div className="space-y-3">
      {/* Selected values as tags */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map(v => (
            <span 
              key={v}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--accent)]/20 text-[var(--accent)] text-sm"
            >
              {v}
              <button 
                type="button"
                onClick={() => removeValue(v)}
                className="hover:bg-white/10 rounded p-0.5"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Options checkboxes or manual input */}
      {loading ? (
        <div className="flex items-center gap-2 text-gray-400 text-sm py-3">
          <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
          </svg>
          Loading {field.optionsEndpoint}...
        </div>
      ) : options.length > 0 ? (
        <div className="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto p-2 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)]">
          {options.map(opt => (
            <label 
              key={opt.value}
              className={`flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-colors ${
                value.includes(opt.value) 
                  ? 'bg-[var(--accent)]/10 border border-[var(--accent)]/30' 
                  : 'hover:bg-[rgba(255,255,255,0.04)] border border-transparent'
              }`}
            >
              <input
                type="checkbox"
                checked={value.includes(opt.value)}
                onChange={() => toggleOption(opt.value)}
                className="w-4 h-4 rounded border-gray-600 text-[var(--accent)] focus:ring-[var(--accent)] focus:ring-offset-0 bg-transparent"
              />
              <span className="text-sm text-white truncate">{opt.label}</span>
            </label>
          ))}
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            type="text"
            value={manualInput}
            onChange={(e) => setManualInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addManualValue())}
            placeholder={field.placeholder || 'Enter value and press Enter'}
            className="flex-1 px-4 py-3 rounded-xl bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] text-white placeholder:text-gray-500 focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] focus:outline-none transition-all"
          />
          <button
            type="button"
            onClick={addManualValue}
            disabled={!manualInput.trim()}
            className="px-4 py-2 rounded-xl bg-[var(--accent)] text-white text-sm font-medium disabled:opacity-50"
          >
            Add
          </button>
        </div>
      )}

      {/* Error message */}
      {error && (
        <p className="text-xs text-amber-400">{error} — Enter values manually above</p>
      )}

      {/* Refresh button */}
      {field.dynamicOptions && stackId && nodeId && (
        <button
          type="button"
          onClick={fetchOptions}
          className="text-xs text-gray-400 hover:text-white flex items-center gap-1"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh {field.optionsEndpoint}
        </button>
      )}

      {field.helperText && (
        <p className="text-xs text-gray-500">{field.helperText}</p>
      )}
    </div>
  );
}

export default function NodeConfigModal({ node, stackId, onSave, onClose }: NodeConfigModalProps) {
  const tool = getToolById(node.toolType);
  const [config, setConfig] = useState<Record<string, any>>(node.config || {});
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // OAuth state for GitHub
  const isOAuthTool = OAUTH_TOOLS.includes(node.toolType);
  const [useOAuth, setUseOAuth] = useState(isOAuthTool);
  const [githubInfo, setGithubInfo] = useState<GitHubConnectionInfo | null>(null);
  const [loadingGithub, setLoadingGithub] = useState(false);

  // Check for existing GitHub OAuth connection
  useEffect(() => {
    if (isOAuthTool) {
      checkGitHubConnection();
    }
  }, [isOAuthTool]);

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
          // Pre-fill config with linked integration
          setConfig(prev => ({
            ...prev,
            _integration_id: githubIntegration.id,
            _oauth_linked: true,
          }));
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
    // Store node info in sessionStorage so we can update it after OAuth
    sessionStorage.setItem('pending_github_node', JSON.stringify({ nodeId: node.id, stackId }));
    window.location.href = '/api/integrations/oauth/github';
  };

  // Get config fields - use tool's fields or provide a fallback
  const configFields: ConfigField[] = tool?.configFields || [
    { name: 'api_key', label: 'API Key', type: 'password', required: true, placeholder: 'Your API key' },
  ];

  const handleFieldChange = (name: string, value: any) => {
    setConfig(prev => ({ ...prev, [name]: value }));
    setTestResult(null);
  };

  const handleFileUpload = async (name: string, file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const content = e.target?.result as string;
        // Try to parse as JSON for manifest files
        if (file.name.endsWith('.json')) {
          JSON.parse(content); // Validate JSON
        }
        handleFieldChange(name, content);
      } catch (error) {
        setTestResult({ success: false, message: 'Invalid file format' });
      }
    };
    reader.readAsText(file);
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);

    try {
      const res = await fetch('/api/pipeline/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          toolType: node.toolType,
          config,
        }),
      });

      const data = await res.json();
      setTestResult({ success: data.success, message: data.message });
    } catch (error) {
      setTestResult({ success: false, message: 'Connection test failed' });
    } finally {
      setTesting(false);
    }
  };

  const isValid = configFields.every(field => {
    if (!field.required) return true;
    const value = config[field.name];
    // For multi-select, check array has items
    if (field.type === 'multi-select') {
      return Array.isArray(value) && value.length > 0;
    }
    // For other types, check non-empty string
    return value && String(value).trim() !== '';
  });

  const layerColor = LAYER_COLORS[node.layer];

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-lg bg-[#0A0A0F] rounded-2xl border border-[rgba(255,255,255,0.08)] shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-6 py-5 border-b border-[rgba(255,255,255,0.06)]"
          style={{ background: `linear-gradient(135deg, ${layerColor}10, transparent)` }}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div 
                className="w-12 h-12 rounded-xl flex items-center justify-center"
                style={{ backgroundColor: layerColor + '20' }}
              >
                <svg 
                  className="w-6 h-6" 
                  viewBox="0 0 24 24" 
                  fill="none" 
                  stroke={layerColor}
                  strokeWidth="2"
                >
                  <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                  <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-semibold text-white">
                  Configure {node.name}
                </h2>
                <p className="text-sm text-gray-400">{tool?.description || 'Connect this tool to Pallisade'}</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-[rgba(255,255,255,0.06)] text-gray-400 hover:text-white transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5 max-h-[60vh] overflow-y-auto">
          {/* OAuth section for GitHub */}
          {isOAuthTool && (
            <div className="mb-6">
              {loadingGithub ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
                </div>
              ) : githubInfo?.connected ? (
                // Already connected via OAuth
                <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                  <div className="flex items-center gap-3">
                    {githubInfo.avatar ? (
                      <img src={githubInfo.avatar} alt="" className="w-10 h-10 rounded-full" />
                    ) : (
                      <div className="w-10 h-10 rounded-full bg-[#24292e] flex items-center justify-center">
                        <GitHubIcon className="w-5 h-5 text-white" />
                      </div>
                    )}
                    <div className="flex-1">
                      <div className="flex items-center gap-2 text-emerald-400 mb-0.5">
                        <Check className="w-4 h-4" />
                        <span className="font-medium text-sm">GitHub Connected</span>
                      </div>
                      <p className="text-white text-sm">@{githubInfo.username}</p>
                      <p className="text-xs text-gray-400">{githubInfo.repoCount} repositories available</p>
                    </div>
                    <button
                      onClick={handleGitHubConnect}
                      className="text-xs text-gray-400 hover:text-white underline"
                    >
                      Reconnect
                    </button>
                  </div>
                </div>
              ) : (
                // Not connected - show OAuth button
                <div className="text-center py-6">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-[#24292e] flex items-center justify-center">
                    <GitHubIcon className="w-8 h-8 text-white" />
                  </div>
                  <h3 className="text-lg font-medium text-white mb-2">Connect to GitHub</h3>
                  <p className="text-sm text-gray-400 mb-6 max-w-sm mx-auto">
                    Sign in with GitHub to access your repositories for creating PRs and tracking changes.
                  </p>

                  <button
                    onClick={handleGitHubConnect}
                    className="inline-flex items-center gap-2 px-6 py-3 bg-[#24292e] hover:bg-[#2d3339] text-white font-medium rounded-lg transition-colors"
                  >
                    <GitHubIcon className="w-5 h-5" />
                    Connect with GitHub
                    <ExternalLink className="w-4 h-4 ml-1 opacity-50" />
                  </button>

                  <div className="mt-4 pt-4 border-t border-[rgba(255,255,255,0.06)]">
                    <button
                      onClick={() => setUseOAuth(false)}
                      className="text-xs text-gray-500 hover:text-gray-300"
                    >
                      Or configure manually with Personal Access Token →
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Manual config fields (shown if not using OAuth or if OAuth is connected) */}
          {(!isOAuthTool || !useOAuth || githubInfo?.connected) && configFields.map(field => (
            <div key={field.name}>
              <label className="block text-sm font-medium text-white mb-2">
                {field.label}
                {field.required && <span className="text-red-400 ml-1">*</span>}
              </label>
              
              {field.type === 'file' ? (
                <div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={field.name === 'manifest' ? '.json' : '.json,.pem,.key'}
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleFileUpload(field.name, file);
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="w-full px-4 py-4 rounded-xl border-2 border-dashed border-[rgba(255,255,255,0.1)] hover:border-[var(--accent)] hover:bg-[var(--accent)]/5 text-sm transition-all"
                  >
                    {config[field.name] ? (
                      <span className="flex items-center justify-center gap-2 text-emerald-400">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                        File uploaded successfully
                      </span>
                    ) : (
                      <span className="flex items-center justify-center gap-2 text-gray-400">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                        </svg>
                        Click to upload file
                      </span>
                    )}
                  </button>
                  {field.helperText && (
                    <p className="text-xs text-gray-500 mt-2">{field.helperText}</p>
                  )}
                </div>
              ) : field.type === 'multi-select' ? (
                <MultiSelectField
                  field={field}
                  value={config[field.name] || []}
                  onChange={(value) => handleFieldChange(field.name, value)}
                  stackId={stackId}
                  nodeId={node.id}
                  toolType={node.toolType}
                  config={config}
                />
              ) : field.type === 'select' ? (
                <select
                  value={config[field.name] || ''}
                  onChange={(e) => handleFieldChange(field.name, e.target.value)}
                  className="w-full px-4 py-3 rounded-xl bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] text-white focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] focus:outline-none transition-all"
                >
                  <option value="">Select...</option>
                  {field.options?.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              ) : field.type === 'textarea' ? (
                <textarea
                  value={config[field.name] || ''}
                  onChange={(e) => handleFieldChange(field.name, e.target.value)}
                  placeholder={field.placeholder}
                  rows={4}
                  className="w-full px-4 py-3 rounded-xl bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] text-white placeholder:text-gray-500 focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] focus:outline-none transition-all resize-none"
                />
              ) : (
                <input
                  type={field.type}
                  value={config[field.name] || ''}
                  onChange={(e) => handleFieldChange(field.name, e.target.value)}
                  placeholder={field.placeholder}
                  className="w-full px-4 py-3 rounded-xl bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] text-white placeholder:text-gray-500 focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] focus:outline-none transition-all"
                />
              )}
            </div>
          ))}

          {/* Test Result */}
          {testResult && (
            <div className={`p-4 rounded-xl flex items-center gap-3 ${
              testResult.success 
                ? 'bg-emerald-500/10 border border-emerald-500/20' 
                : 'bg-red-500/10 border border-red-500/20'
            }`}>
              {testResult.success ? (
                <svg className="w-5 h-5 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              ) : (
                <svg className="w-5 h-5 text-red-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              )}
              <span className={testResult.success ? 'text-emerald-400' : 'text-red-400'}>
                {testResult.message}
              </span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[rgba(255,255,255,0.06)] bg-[rgba(0,0,0,0.2)] flex items-center justify-between">
          <button
            onClick={testConnection}
            disabled={!isValid || testing}
            className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl bg-[rgba(255,255,255,0.04)] hover:bg-[rgba(255,255,255,0.08)] text-white border border-[rgba(255,255,255,0.08)] hover:border-[rgba(255,255,255,0.12)] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {testing ? (
              <>
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
                </svg>
                Testing...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Test Connection
              </>
            )}
          </button>
          
          <div className="flex items-center gap-3">
            <button 
              onClick={onClose} 
              className="px-4 py-2.5 text-sm font-medium rounded-xl text-gray-400 hover:text-white hover:bg-[rgba(255,255,255,0.04)] transition-all"
            >
              Cancel
            </button>
            <button
              onClick={() => onSave(config)}
              disabled={!isValid && !(isOAuthTool && githubInfo?.connected)}
              className="px-5 py-2.5 text-sm font-medium rounded-xl bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Save Configuration
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// GitHub Icon Component
function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
    </svg>
  );
}
