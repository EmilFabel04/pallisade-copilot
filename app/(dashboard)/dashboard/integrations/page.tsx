'use client';

import { useState, useEffect } from 'react';

// Integration definitions - only notifications and issue tracking
// Data pipeline tools are configured in the Pipeline Builder
const INTEGRATIONS = {
  notifications: [
    { type: 'SLACK', name: 'Slack', desc: 'Channel alerts', color: '#E01E5A', popular: true },
    { type: 'PAGERDUTY', name: 'PagerDuty', desc: 'Incident escalation', color: '#06AC38' },
    { type: 'OPSGENIE', name: 'Opsgenie', desc: 'Alert management', color: '#2684FF' },
    { type: 'TEAMS', name: 'MS Teams', desc: 'Microsoft Teams', color: '#6264A7' },
    { type: 'EMAIL', name: 'Email', desc: 'Email notifications', color: '#EA4335' },
  ],
  ticketing: [
    { type: 'JIRA', name: 'Jira', desc: 'Issue tracking', color: '#0052CC', popular: true },
    { type: 'LINEAR', name: 'Linear', desc: 'Issue tracking', color: '#5E6AD2' },
    { type: 'ASANA', name: 'Asana', desc: 'Task management', color: '#F06A6A' },
    { type: 'SERVICENOW', name: 'ServiceNow', desc: 'ITSM platform', color: '#62D84E' },
  ],
};

// Credential field definitions - only notifications and ticketing
const CREDENTIAL_FIELDS: Record<string, { name: string; key: string; type?: string; placeholder: string; required?: boolean }[]> = {
  // Notifications
  SLACK: [
    { name: 'Webhook URL', key: 'webhookUrl', placeholder: 'https://hooks.slack.com/services/...', required: true },
    { name: 'Channel Name', key: 'channel', placeholder: '#data-alerts' },
  ],
  PAGERDUTY: [
    { name: 'API Key', key: 'api_key', type: 'password', placeholder: 'your-api-key', required: true },
    { name: 'Service ID', key: 'service_id', placeholder: 'P12345', required: true },
    { name: 'Routing Key', key: 'routing_key', type: 'password', placeholder: 'your-routing-key', required: true },
  ],
  OPSGENIE: [
    { name: 'API Key', key: 'api_key', type: 'password', placeholder: 'your-api-key', required: true },
    { name: 'Team Name', key: 'team', placeholder: 'data-team' },
    { name: 'Region', key: 'region', placeholder: 'us (or eu)' },
  ],
  TEAMS: [
    { name: 'Webhook URL', key: 'webhook_url', placeholder: 'https://outlook.office.com/webhook/...', required: true },
  ],
  EMAIL: [
    { name: 'Recipients', key: 'recipients', placeholder: 'alerts@company.com, team@company.com', required: true },
    { name: 'Provider', key: 'provider', placeholder: 'resend (or sendgrid)' },
    { name: 'API Key', key: 'api_key', type: 'password', placeholder: 're_...', required: true },
  ],
  // Ticketing
  JIRA: [
    { name: 'Site URL', key: 'site_url', placeholder: 'https://your-company.atlassian.net', required: true },
    { name: 'Email', key: 'email', placeholder: 'you@company.com', required: true },
    { name: 'API Token', key: 'api_token', type: 'password', placeholder: 'ATATT3...', required: true },
    { name: 'Project Key', key: 'project_key', placeholder: 'DATA', required: true },
  ],
  LINEAR: [
    { name: 'API Key', key: 'api_key', type: 'password', placeholder: 'lin_api_...', required: true },
    { name: 'Team ID', key: 'team_id', placeholder: 'your-team-id', required: true },
  ],
  ASANA: [
    { name: 'Access Token', key: 'access_token', type: 'password', placeholder: '1/...', required: true },
    { name: 'Workspace ID', key: 'workspace_id', placeholder: '12345', required: true },
    { name: 'Project ID', key: 'project_id', placeholder: '67890', required: true },
  ],
  SERVICENOW: [
    { name: 'Instance URL', key: 'instance_url', placeholder: 'https://your-instance.service-now.com', required: true },
    { name: 'Username', key: 'username', placeholder: 'admin', required: true },
    { name: 'Password', key: 'password', type: 'password', placeholder: '••••••••', required: true },
  ],
};

// Category icons - only notifications and ticketing
const CATEGORY_CONFIG: Record<string, { icon: React.ReactNode; color: string; title: string; desc: string }> = {
  notifications: {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
      </svg>
    ),
    color: 'pink',
    title: 'Notifications',
    desc: 'Alerts & incident management',
  },
  ticketing: {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16.5 6v.75m0 3v.75m0 3v.75m0 3V18m-9-5.25h5.25M7.5 15h3M3.375 5.25c-.621 0-1.125.504-1.125 1.125v3.026a2.999 2.999 0 010 5.198v3.026c0 .621.504 1.125 1.125 1.125h17.25c.621 0 1.125-.504 1.125-1.125v-3.026a2.999 2.999 0 010-5.198V6.375c0-.621-.504-1.125-1.125-1.125H3.375z" />
      </svg>
    ),
    color: 'indigo',
    title: 'Issue Tracking',
    desc: 'Create tickets from findings',
  },
};

const COLOR_MAP: Record<string, string> = {
  blue: 'bg-blue-500/10 text-blue-400',
  purple: 'bg-purple-500/10 text-purple-400',
  orange: 'bg-orange-500/10 text-orange-400',
  pink: 'bg-pink-500/10 text-pink-400',
  indigo: 'bg-indigo-500/10 text-indigo-400',
  teal: 'bg-teal-500/10 text-teal-400',
};

interface Integration {
  id: string;
  name: string;
  type: string;
  status: string;
  connectionInfo?: string;
  scanCount?: number;
  createdAt?: string;
  updatedAt?: string;
}

export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [savedConnections, setSavedConnections] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [expandedCategory, setExpandedCategory] = useState<string | null>('notifications');
  
  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [modalType, setModalType] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [integrationName, setIntegrationName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [selectedSavedId, setSelectedSavedId] = useState<string>('');

  useEffect(() => {
    fetchIntegrations();
    fetchSavedConnections();
    
    const params = new URLSearchParams(window.location.search);
    if (params.get('success')) {
      setMessage({ type: 'success', text: 'Integration connected successfully!' });
      window.history.replaceState({}, '', '/dashboard/integrations');
      setTimeout(() => setMessage(null), 5000);
    } else if (params.get('error')) {
      setMessage({ type: 'error', text: `Connection failed: ${params.get('error')}` });
      window.history.replaceState({}, '', '/dashboard/integrations');
      setTimeout(() => setMessage(null), 8000);
    }
  }, []);

  const fetchIntegrations = async () => {
    try {
      const res = await fetch('/api/integrations');
      const data = await res.json();
      setIntegrations(data.integrations || []);
    } catch (e) {
      console.error('Failed to fetch:', e);
    } finally {
      setLoading(false);
    }
  };

  const fetchSavedConnections = async () => {
    try {
      const res = await fetch('/api/integrations/saved');
      const data = await res.json();
      setSavedConnections(data.connections || []);
    } catch (e) {
      console.error('Failed to fetch saved connections:', e);
    }
  };

  const findIntegrationDef = (type: string) => {
    for (const category of Object.values(INTEGRATIONS)) {
      const found = category.find(i => i.type === type);
      if (found) return found;
    }
    return null;
  };

  const handleConnect = async (type: string, oauth?: boolean) => {
    if (oauth) {
      window.location.href = `/api/integrations/oauth/${type.toLowerCase()}`;
      return;
    }
    const def = findIntegrationDef(type);
    setModalType(type);
    setCredentials({});
    setIntegrationName(def?.name || type);
    setTestResult(null);
    setSelectedSavedId('');
    setShowModal(true);
  };

  const handleDisconnect = async (id: string) => {
    if (!confirm('Disconnect this integration?')) return;
    
    // Optimistic update - immediately update UI
    setIntegrations(prev => prev.map(i => 
      i.id === id ? { ...i, status: 'INACTIVE' } : i
    ));
    setMessage({ type: 'success', text: 'Integration disconnected' });
    setTimeout(() => setMessage(null), 3000);
    
    try {
      await fetch(`/api/integrations/${id}`, { 
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'INACTIVE' })
      });
      // Refresh from server in background to ensure consistency
      Promise.all([fetchIntegrations(), fetchSavedConnections()]);
    } catch {
      // Revert on error
      await Promise.all([fetchIntegrations(), fetchSavedConnections()]);
      setMessage({ type: 'error', text: 'Failed to disconnect' });
      setTimeout(() => setMessage(null), 3000);
    }
  };

  const handleRemove = async (id: string) => {
    if (!confirm('Permanently remove this integration (credentials will be deleted)?')) return;
    
    // Optimistic update - immediately remove from UI
    setIntegrations(prev => prev.filter(i => i.id !== id));
    setSavedConnections(prev => prev.filter(c => c.id !== id));
    setMessage({ type: 'success', text: 'Integration removed' });
    setTimeout(() => setMessage(null), 3000);
    
    try {
      await fetch(`/api/integrations/${id}`, { method: 'DELETE' });
      // Refresh from server in background to ensure consistency
      Promise.all([fetchIntegrations(), fetchSavedConnections()]);
    } catch {
      // Revert on error
      await Promise.all([fetchIntegrations(), fetchSavedConnections()]);
      setMessage({ type: 'error', text: 'Failed to remove integration' });
      setTimeout(() => setMessage(null), 3000);
    }
  };

  const handleTestConnection = async () => {
    if (!modalType) return;
    if (selectedSavedId) {
      setTestResult({ success: true, message: 'Using saved connection — credentials already stored.' });
      return;
    }
    setIsTesting(true);
    setTestResult(null);
    
    try {
      const res = await fetch('/api/integrations/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: modalType, credentials }),
      });
      const data = await res.json();
      setTestResult({ 
        success: data.success, 
        message: data.message || data.error || (data.success ? 'Connection successful!' : 'Connection failed'),
        tables: data.metadata?.tables || [],
      } as any);
    } catch {
      setTestResult({ success: false, message: 'Failed to test connection' });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSaveIntegration = async () => {
    if (!modalType) return;
    setIsSubmitting(true);
    
    try {
      // If user selected a saved connection, just activate/update it
      if (selectedSavedId) {
        const res = await fetch(`/api/integrations/${selectedSavedId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'ACTIVE', name: integrationName || undefined }),
        });
        const data = await res.json();

        if (res.ok) {
          setShowModal(false);
          setMessage({ type: 'success', text: `${integrationName} activated successfully!` });
          setTimeout(() => setMessage(null), 5000);
          await Promise.all([fetchIntegrations(), fetchSavedConnections()]);
        } else {
          setMessage({ type: 'error', text: data.error || 'Failed to activate connection' });
          setTimeout(() => setMessage(null), 5000);
        }
        return;
      }

      const res = await fetch('/api/integrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: modalType,
          name: integrationName,
          credentials: credentials,
        }),
      });
      
      const data = await res.json();
      
      if (res.ok) {
        setShowModal(false);
        setMessage({ type: 'success', text: `${integrationName} connected successfully!` });
        setTimeout(() => setMessage(null), 5000);
        await Promise.all([fetchIntegrations(), fetchSavedConnections()]);
        
        if (data.integration?.id) {
          await fetch(`/api/integrations/${data.integration.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'ACTIVE' }),
          });
          await Promise.all([fetchIntegrations(), fetchSavedConnections()]);
        }
      } else {
        setMessage({ type: 'error', text: data.error || 'Failed to save integration' });
        setTimeout(() => setMessage(null), 5000);
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to save integration' });
      setTimeout(() => setMessage(null), 5000);
    } finally {
      setIsSubmitting(false);
    }
  };

  const isConnected = (type: string) => 
    integrations.some(i => i.type === type && i.status === 'ACTIVE');

  const getIntegration = (type: string) => 
    integrations.find(i => i.type === type && i.status === 'ACTIVE');

  const connectedCount = integrations.filter(i => i.status === 'ACTIVE').length;

  // Count connected by category
  const getConnectedInCategory = (category: keyof typeof INTEGRATIONS) => {
    return INTEGRATIONS[category].filter(int => isConnected(int.type)).length;
  };

  const availableSaved = modalType
    ? Array.from(
        new Map(
          [...integrations, ...savedConnections]
            .filter(c => c.type === modalType)
            .map(c => [c.id, c])
        ).values()
      )
    : [];
  const disableCredentials = !!selectedSavedId;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Toast */}
      {message && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-fadeIn ${
          message.type === 'success' 
            ? 'bg-emerald-950 border border-emerald-800 text-emerald-400' 
            : 'bg-red-950 border border-red-800 text-red-400'
        }`}>
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {message.type === 'success' 
              ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            }
          </svg>
          <span className="font-medium text-sm">{message.text}</span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between">
      <div>
        <h1 className="text-2xl font-bold">Notifications & Issue Tracking</h1>
          <p className="text-[var(--muted)] mt-1">Configure alerts and ticketing for data quality findings</p>
        </div>
        <div className="flex items-center gap-4">
          {connectedCount > 0 && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-500/10 rounded-lg">
              <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-sm font-medium text-emerald-400">{connectedCount} connected</span>
            </div>
          )}
        </div>
      </div>

      {/* Integration Categories */}
      <div className="space-y-3">
        {(Object.entries(INTEGRATIONS) as [keyof typeof INTEGRATIONS, typeof INTEGRATIONS[keyof typeof INTEGRATIONS]][]).map(([category, items]) => {
          const config = CATEGORY_CONFIG[category];
          const connectedInCategory = getConnectedInCategory(category);
          const isExpanded = expandedCategory === category;
          
          return (
            <div key={category} className="dashboard-card overflow-hidden">
              {/* Category Header */}
              <button
                onClick={() => setExpandedCategory(isExpanded ? null : category)}
                className="w-full p-4 flex items-center gap-4 hover:bg-[rgba(255,255,255,0.02)] transition-colors"
              >
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${COLOR_MAP[config.color]}`}>
                  {config.icon}
                  </div>
                <div className="flex-1 text-left">
                  <div className="flex items-center gap-3">
                    <h2 className="font-semibold">{config.title}</h2>
                    {connectedInCategory > 0 && (
                      <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-emerald-500/10 text-emerald-400">
                        {connectedInCategory} connected
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-[var(--muted)]">{config.desc}</p>
                </div>
                <div className="flex items-center gap-2 text-[var(--muted)]">
                  <span className="text-sm">{items.length} integrations</span>
                  <svg 
                    className={`w-5 h-5 transition-transform ${isExpanded ? 'rotate-180' : ''}`} 
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </button>

              {/* Integration Cards (Expandable) */}
              {isExpanded && (
                <div className="px-4 pb-4 pt-2 border-t border-[rgba(255,255,255,0.04)]">
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                    {items.map(int => {
                      const connected = isConnected(int.type);
                      const integration = getIntegration(int.type);
                      
                      return (
                        <div 
                          key={int.type}
                          className={`relative p-4 rounded-xl border transition-all ${
                            connected 
                              ? 'bg-emerald-500/5 border-emerald-500/20' 
                              : 'bg-[rgba(255,255,255,0.02)] border-[rgba(255,255,255,0.06)] hover:border-[rgba(255,255,255,0.12)]'
                          }`}
                        >
                          {'popular' in int && int.popular && !connected && (
                            <span className="absolute -top-2 -right-2 px-2 py-0.5 text-[10px] font-bold uppercase rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
                              Popular
                            </span>
                          )}
                          
                          <div className="flex items-start gap-3">
                            <div 
                              className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                              style={{ backgroundColor: `${int.color}15` }}
                            >
                              {int.type === 'GITHUB' ? (
                                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                                  <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
                                </svg>
                              ) : (
                                <span className="text-sm font-bold" style={{ color: int.color === '#fff' ? '#888' : int.color }}>
                                  {int.name.substring(0, 2).toUpperCase()}
                                </span>
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <h3 className="font-medium text-sm truncate">{int.name}</h3>
                                {connected && (
                                  <span className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
                                )}
                              </div>
                              <p className="text-xs text-[var(--muted)] truncate">
                                {connected && integration?.scanCount 
                                  ? `${integration.scanCount} scans` 
                                  : int.desc}
                              </p>
                            </div>
                          </div>
                          
                          <div className="mt-3 flex gap-2">
                            {connected ? (
                              <>
                              <button 
                                onClick={() => handleDisconnect(integration!.id)}
                                  className="flex-1 py-2 text-xs text-[var(--muted)] hover:text-amber-400 transition-colors rounded-lg bg-[rgba(255,255,255,0.04)] hover:bg-[rgba(255,255,255,0.08)]"
                              >
                                Disconnect
                              </button>
                                <button 
                                  onClick={() => handleRemove(integration!.id)}
                                  className="flex-1 py-2 text-xs text-red-400 hover:text-red-300 transition-colors rounded-lg bg-red-500/10 hover:bg-red-500/20"
                                >
                                  Remove
                                </button>
                              </>
                            ) : (
                              <>
                              <button 
                                onClick={() => handleConnect(int.type, 'oauth' in int && int.oauth)}
                                  className="flex-1 py-2 text-xs font-medium rounded-lg bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] transition-colors"
                              >
                                {'oauth' in int && int.oauth ? 'Connect with OAuth' : 'Connect'}
                                </button>
                                {integration && (
                                  <button 
                                    onClick={() => handleRemove(integration.id)}
                                    className="flex-1 py-2 text-xs text-red-400 hover:text-red-300 transition-colors rounded-lg bg-red-500/10 hover:bg-red-500/20"
                                  >
                                    Remove
                              </button>
                                )}
                              </>
                            )}
                          </div>
                </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
        </div>

      {/* Help */}
      <div className="dashboard-card p-5 border-dashed">
        <div className="flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-[var(--accent)]/10 flex items-center justify-center">
            <svg className="w-5 h-5 text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
            </svg>
          </div>
          <div className="flex-1">
            <h3 className="font-semibold">Need a different integration?</h3>
            <p className="text-sm text-[var(--muted)]">We're always adding more. Let us know what you need.</p>
          </div>
          <a href="mailto:support@pallisade.dev" className="text-sm text-[var(--accent-2)] hover:underline">
            Request Integration →
          </a>
        </div>
      </div>

      {/* Credentials Modal */}
      {showModal && modalType && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[var(--card)] border border-[rgba(255,255,255,0.08)] rounded-2xl max-w-lg w-full max-h-[90vh] overflow-y-auto shadow-2xl">
            {/* Modal Header */}
            <div className="p-6 border-b border-[rgba(255,255,255,0.06)]">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div 
                    className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{ backgroundColor: `${findIntegrationDef(modalType)?.color || '#888'}20` }}
                  >
                    <span 
                      className="text-lg font-bold"
                      style={{ color: findIntegrationDef(modalType)?.color || '#888' }}
                    >
                      {modalType.substring(0, 2)}
                    </span>
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold">Connect {integrationName}</h2>
                    <p className="text-sm text-[var(--muted)]">Enter your credentials</p>
                  </div>
                </div>
                <button 
                  onClick={() => { setShowModal(false); setSelectedSavedId(''); }}
                  className="p-2 hover:bg-[rgba(255,255,255,0.05)] rounded-lg transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">Display Name</label>
                <input
                  type="text"
                  value={integrationName}
                  onChange={(e) => setIntegrationName(e.target.value)}
                  placeholder="e.g., Production Snowflake"
                  className="w-full px-4 py-2.5 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg focus:outline-none focus:border-[var(--accent)] transition-colors text-sm"
                />
              </div>

              <div className="p-4 rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.02)] space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium">Use a saved connection</div>
                  {selectedSavedId && (
                    <button
                      onClick={() => {
                        setSelectedSavedId('');
                        setTestResult(null);
                      }}
                      className="text-xs text-[var(--muted)] hover:text-[var(--text)]"
                    >
                      Clear
                    </button>
                  )}
                </div>
                {availableSaved.length > 0 ? (
                  <div className="space-y-2">
                    {availableSaved.map((conn) => (
                      <label
                        key={conn.id}
                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                          selectedSavedId === conn.id
                            ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                            : 'border-[rgba(255,255,255,0.08)] hover:border-[rgba(255,255,255,0.16)]'
                        }`}
                      >
                        <input
                          type="radio"
                          className="mt-1"
                          checked={selectedSavedId === conn.id}
                          onChange={() => {
                            setSelectedSavedId(conn.id);
                            setCredentials({});
                            setTestResult(null);
                            setIntegrationName(conn.name || integrationName);
                          }}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2">
                            <div className="font-medium text-sm truncate">{conn.name}</div>
                            <span className="text-[10px] uppercase text-[var(--muted)]">{conn.status}</span>
                          </div>
                          <div className="text-xs text-[var(--muted)] truncate">
                            {conn.connectionInfo || 'Saved connection'}
                          </div>
                          <div className="text-[10px] text-[var(--muted)]">
                            Last updated: {conn.updatedAt ? new Date(conn.updatedAt).toLocaleDateString() : '—'}
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-[var(--muted)]">
                    No saved connections for this type yet.
                  </div>
                )}
                <p className="text-xs text-[var(--muted)]">
                  Selecting a saved connection will reuse stored credentials—no need to re-enter details.
                </p>
              </div>

              {CREDENTIAL_FIELDS[modalType]?.map((field) => (
                <div key={field.key}>
                  <label className="block text-sm font-medium mb-2">
                    {field.name}
                    {field.required && <span className="text-red-400 ml-1">*</span>}
                  </label>
                  {field.type === 'textarea' ? (
                    <textarea
                      value={credentials[field.key] || ''}
                      onChange={(e) => setCredentials({ ...credentials, [field.key]: e.target.value })}
                      placeholder={field.placeholder}
                      rows={4}
                      disabled={disableCredentials}
                      className={`w-full px-4 py-2.5 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg focus:outline-none focus:border-[var(--accent)] transition-colors text-sm font-mono resize-none ${disableCredentials ? 'opacity-60 cursor-not-allowed' : ''}`}
                    />
                  ) : (
                    <input
                      type={field.type || 'text'}
                      value={credentials[field.key] || ''}
                      onChange={(e) => setCredentials({ ...credentials, [field.key]: e.target.value })}
                      placeholder={field.placeholder}
                      disabled={disableCredentials}
                      className={`w-full px-4 py-2.5 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg focus:outline-none focus:border-[var(--accent)] transition-colors text-sm ${disableCredentials ? 'opacity-60 cursor-not-allowed' : ''}`}
                    />
                  )}
                </div>
              ))}

              {testResult && (
                <div className={`rounded-lg overflow-hidden ${
                  testResult.success 
                    ? 'bg-emerald-500/10 border border-emerald-500/20' 
                    : 'bg-red-500/10 border border-red-500/20'
                }`}>
                  <div className="p-4 flex items-center gap-3">
                    <svg className={`w-5 h-5 flex-shrink-0 ${testResult.success ? 'text-emerald-400' : 'text-red-400'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      {testResult.success ? (
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      ) : (
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      )}
                    </svg>
                    <span className={`text-sm font-medium ${testResult.success ? 'text-emerald-400' : 'text-red-400'}`}>
                      {testResult.message}
                    </span>
                  </div>
                  {/* Show discovered tables */}
                  {testResult.success && (testResult as any).tables && (testResult as any).tables.length > 0 && (
                    <div className="px-4 pb-4">
                      <div className="text-xs text-emerald-300 mb-2 font-medium">
                        {(testResult as any).tables.length} tables discovered:
                      </div>
                      <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
                        {(testResult as any).tables.slice(0, 12).map((table: string) => (
                          <span key={table} className="px-2 py-1 bg-emerald-500/15 rounded text-xs font-mono text-emerald-300">
                            {table}
                          </span>
                        ))}
                        {(testResult as any).tables.length > 12 && (
                          <span className="px-2 py-1 text-xs text-emerald-400">
                            +{(testResult as any).tables.length - 12} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-6 border-t border-[rgba(255,255,255,0.06)] flex items-center justify-between gap-4">
              <button
                onClick={handleTestConnection}
                disabled={isTesting}
                className="px-4 py-2.5 text-sm font-medium rounded-lg bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {isTesting ? (
                  <>
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Testing...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    Test Connection
                  </>
                )}
              </button>
              
              <div className="flex items-center gap-3">
                <button
                  onClick={() => { setShowModal(false); setSelectedSavedId(''); }}
                  className="px-4 py-2.5 text-sm font-medium text-[var(--muted)] hover:text-[var(--text)] transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveIntegration}
                  disabled={isSubmitting || !integrationName}
                  className="px-5 py-2.5 text-sm font-medium rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                  {isSubmitting ? (
                    <>
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Connecting...
                    </>
                  ) : (
                    'Connect'
                  )}
          </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
