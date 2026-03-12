'use client';

import { useState, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import { MonitorConfigForm } from './MonitorConfigForm';
import type { ScheduledTask } from '@/types/schedule';
import {
  type MonitorDefinition,
  type MonitorCategory,
  getMonitorDefinition,
  TOOL_MONITOR_TYPES,
} from '@/types/monitor-catalog';

interface MonitorGroup {
  category: MonitorCategory;
  label: string;
  monitors: MonitorDefinition[];
}

interface IntegrationNode {
  id: string;
  name: string;
  toolType: string;
  layer: string;
  integrationId: string | null;
  sourceMode: string | null;
  hasLiveConnection: boolean;
}

export interface MonitorPrefillData {
  name: string;
  monitorType: string;
  targetFqn?: string;
  config?: Record<string, any>;
  integrationId?: string;
}

interface CreateTaskModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (task: any) => void;
  onUpdate?: (taskId: string, task: any) => void;
  editTask?: ScheduledTask | null;
  prefillData?: MonitorPrefillData | null;
  integrations?: Array<{ id: string; name: string; type: string }>;
  stackId?: string;
}

export function CreateTaskModal({ open, onClose, onSubmit, onUpdate, editTask, prefillData, integrations = [], stackId }: CreateTaskModalProps) {
  const [step, setStep] = useState(1);
  const isEditing = !!editTask;

  // Step 1: Mode + content
  const [taskMode, setTaskMode] = useState<'prompt' | 'structured'>('prompt');
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [monitorType, setMonitorType] = useState('');
  const [targetFqn, setTargetFqn] = useState('');
  const [config, setConfig] = useState<Record<string, any>>({});

  // Step 2: Schedule
  const [schedule, setSchedule] = useState('0 8 * * *');
  const [timezone, setTimezone] = useState('UTC');

  // Step 3: Alerts
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);
  const [integrationId, setIntegrationId] = useState('');
  const [connectedChannels, setConnectedChannels] = useState<string[]>(['email']);

  // Catalog data
  const [groupedMonitors, setGroupedMonitors] = useState<MonitorGroup[]>([]);
  const [integrationNodes, setIntegrationNodes] = useState<IntegrationNode[]>([]);

  // Fetch monitor catalog when modal opens
  useEffect(() => {
    if (!open) return;
    const url = stackId
      ? `/api/schedule/monitor-catalog?stackId=${stackId}`
      : '/api/schedule/monitor-catalog';
    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        setGroupedMonitors(data.grouped || []);
        setIntegrationNodes(data.integrationNodes || []);
      })
      .catch(() => {
        setGroupedMonitors([]);
        setIntegrationNodes([]);
      });
  }, [open, stackId]);

  // Pre-fill form when editing an existing task or from recommendation prefill
  useEffect(() => {
    if (editTask) {
      setName(editTask.name);
      setTaskMode(editTask.taskMode);
      setPrompt(editTask.prompt || '');
      setMonitorType(editTask.monitorType || '');
      setTargetFqn(editTask.targetFqn || '');
      setConfig(editTask.config || {});
      setSchedule(editTask.schedule);
      setTimezone(editTask.timezone);
      setAlertChannels(editTask.alertChannels || []);
      setAlertOnStatus(editTask.alertOnStatus || ['FAIL', 'WARN', 'ERROR']);
      setIntegrationId(editTask.integrationId || '');
      setStep(1);
    } else if (prefillData && open) {
      setName(prefillData.name);
      setTaskMode('structured');
      setPrompt('');
      setMonitorType(prefillData.monitorType);
      setTargetFqn(prefillData.targetFqn || '');
      setConfig(prefillData.config || {});
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setIntegrationId(prefillData.integrationId || '');
      setStep(1);
    } else if (open) {
      setName('');
      setTaskMode('prompt');
      setPrompt('');
      setMonitorType('');
      setTargetFqn('');
      setConfig({});
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setIntegrationId('');
      setStep(1);
    }
  }, [editTask, prefillData, open]);

  // Fetch connected channel status when modal opens
  useEffect(() => {
    if (!open) return;
    const channels = ['email'];
    fetch('/api/integrations/slack')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data?.connected) channels.push('slack');
        setConnectedChannels(channels);
      })
      .catch(() => setConnectedChannels(channels));
  }, [open]);

  if (!open) return null;

  // Get the selected monitor definition from catalog
  const selectedDef = getMonitorDefinition(monitorType);
  const targetType = selectedDef?.target_selector_type || 'fqn';
  const isToolMonitor = TOOL_MONITOR_TYPES.includes(monitorType);
  const isInfraMonitor = targetType === 'server';
  const needsFqnTarget = targetType === 'fqn';

  // Filter integrations based on selected monitor's target type
  const warehouseIntegrations = integrations.filter((i, idx, arr) => {
    const t = i.type.toLowerCase();
    return ['bigquery', 'snowflake', 'postgres', 'redshift'].includes(t) &&
      arr.findIndex((x) => x.id === i.id) === idx;
  });
  const serverIntegrations = integrations.filter((i, idx, arr) => {
    const t = i.type.toLowerCase();
    return ['linux_server'].includes(t) &&
      arr.findIndex((x) => x.id === i.id) === idx;
  });

  // For tool monitors, find matching integration nodes
  const toolIntegrations = isToolMonitor && selectedDef
    ? integrationNodes.filter((n) =>
        selectedDef.required_integrations.includes(n.toolType.toLowerCase())
      )
    : [];

  // Check if any matching tool integration lacks a live API connection
  const selectedToolNode = toolIntegrations.find((n) => n.id === integrationId) || toolIntegrations[0];
  const toolNeedsLiveConnection = isToolMonitor && selectedToolNode && !selectedToolNode.hasLiveConnection;
  const toolConnectionModeLabel = (() => {
    if (!selectedToolNode) return '';
    const mode = selectedToolNode.sourceMode;
    const tool = selectedToolNode.toolType.toLowerCase();
    if (tool === 'airflow' && mode === 'github') return 'GitHub DAG Files';
    if (tool === 'dbt_core') {
      if (mode === 'upload') return 'Manifest Upload';
      if (mode === 'project') return 'Project Upload';
      if (mode === 'github') return 'GitHub Repository';
      return 'Static Files';
    }
    return mode || 'static';
  })();

  // Validation for step 1
  const needsColumn = ['ANOMALY', 'anomaly'].includes(monitorType)
    && config.metric && config.metric !== 'row_count' && config.column !== '*'
    && !config.column?.trim();
  const needsSql = monitorType === 'CUSTOM_SQL' && !config.sql?.trim();
  const needsLogPaths = monitorType === 'LOG_ANALYSIS' && !(config.log_paths?.length > 0);

  // Tool monitor required fields check
  const hasRequiredToolFields = (() => {
    if (!isToolMonitor || !selectedDef) return true;
    return selectedDef.config_schema
      .filter((f) => f.required)
      .every((f) => {
        const val = config[f.key];
        return val !== undefined && val !== null && val !== '';
      });
  })();

  const canProceedStep1 = name.trim() && (
    taskMode === 'prompt'
      ? prompt.trim()
      : (monitorType && (
          isInfraMonitor || isToolMonitor
            ? hasRequiredToolFields && !needsLogPaths
            : (targetFqn.trim() && !needsColumn && !needsSql)
        ))
  );
  const canProceedStep2 = schedule.trim();

  const handleSubmit = () => {
    // For tool monitors, store the integration node ID in config.toolNodeId
    const finalConfig = { ...(config || {}) };
    if (isToolMonitor && integrationId) {
      finalConfig.toolNodeId = integrationId;
    }

    const taskData = {
      name,
      taskMode,
      prompt: taskMode === 'prompt' ? prompt : undefined,
      monitorType: taskMode === 'structured' ? monitorType : undefined,
      targetFqn: taskMode === 'structured' ? (targetFqn || (isInfraMonitor ? 'server' : (isToolMonitor ? (config.connector_id || config.dag_id || config.job_id || monitorType) : undefined))) : undefined,
      config: taskMode === 'structured' ? finalConfig : undefined,
      schedule,
      timezone,
      alertChannels,
      alertOnStatus,
      integrationId: (isToolMonitor ? undefined : integrationId) || undefined,
    };
    if (isEditing && onUpdate) {
      onUpdate(editTask!.id, taskData);
    } else {
      onSubmit(taskData);
    }
  };

  // Determine which integration selector to show
  const renderIntegrationSelector = () => {
    if (taskMode === 'prompt') {
      // Prompt mode: show warehouse selector
      if (warehouseIntegrations.length === 0) return null;
      return (
        <div>
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Run against warehouse
          </label>
          <select
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
          >
            <option value="">Auto-detect</option>
            {warehouseIntegrations.map((i) => (
              <option key={i.id} value={i.id}>{i.name} ({i.type})</option>
            ))}
          </select>
        </div>
      );
    }

    if (!monitorType) return null;

    // Tool monitors: show matching tool integration
    if (isToolMonitor && toolIntegrations.length > 0) {
      return (
        <div className="space-y-2">
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Run against integration
          </label>
          <select
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
          >
            <option value="">Auto-detect</option>
            {toolIntegrations.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name} ({n.toolType}){!n.hasLiveConnection ? ' — static mode' : ''}
              </option>
            ))}
          </select>
          {toolNeedsLiveConnection && (
            <div className="flex items-start gap-2 px-3 py-2.5 bg-amber-500/[0.08] border border-amber-500/[0.2] rounded-lg">
              <svg className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <div className="text-[12px] text-amber-300/90">
                <p className="font-medium mb-0.5">Live API connection required</p>
                <p className="text-amber-300/70">
                  {selectedToolNode?.toolType.toLowerCase() === 'airflow' ? (
                    <>Your Airflow integration &quot;{selectedToolNode.name}&quot; is connected in <strong>{toolConnectionModeLabel}</strong> mode (read-only static files). Monitors need a live Airflow API connection to check DAG run status. Switch the integration to <strong>Airflow API</strong> mode with a host URL to enable monitors.</>
                  ) : selectedToolNode?.toolType.toLowerCase() === 'dbt_core' ? (
                    <>Your dbt integration &quot;{selectedToolNode.name}&quot; is connected in <strong>{toolConnectionModeLabel}</strong> mode. Monitors need a live dbt Cloud API to check job runs and test results. Switch to a <strong>dbt Cloud</strong> integration with an API key to enable monitors.</>
                  ) : (
                    <>This integration is not connected to a live instance. Monitors require a live API connection to work. Update the integration settings to use API mode.</>
                  )}
                </p>
              </div>
            </div>
          )}
        </div>
      );
    }

    // Infra monitors: show server selector
    if (isInfraMonitor && serverIntegrations.length > 0) {
      return (
        <div>
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Run against server
          </label>
          <select
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
          >
            <option value="">Auto-detect</option>
            {serverIntegrations.map((i) => (
              <option key={i.id} value={i.id}>{i.name} ({i.type})</option>
            ))}
          </select>
        </div>
      );
    }

    // Warehouse monitors: show warehouse selector
    if (needsFqnTarget && warehouseIntegrations.length > 0) {
      return (
        <div>
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Run against warehouse
          </label>
          <select
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
          >
            <option value="">Auto-detect</option>
            {warehouseIntegrations.map((i) => (
              <option key={i.id} value={i.id}>{i.name} ({i.type})</option>
            ))}
          </select>
        </div>
      );
    }

    return null;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-3xl mx-4 bg-[var(--surface)] rounded-2xl border border-[var(--subtle-border)] shadow-2xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex-shrink-0 flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <h2 className="text-[16px] font-semibold text-[var(--text)]">{isEditing ? 'Edit Task' : 'Create Scheduled Task'}</h2>
          <button onClick={onClose} className="text-[var(--muted)] hover:text-[var(--text)]">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Step indicators */}
        <div className="flex-shrink-0 flex items-center gap-3 px-6 py-3 border-b border-[var(--border-faint)]">
          {[1, 2, 3].map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div className={cn(
                'w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-medium',
                step === s
                  ? 'bg-[var(--overlay-strong)] text-[var(--text)]'
                  : step > s
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-[var(--overlay-bg)] text-[var(--text-faint)]'
              )}>
                {step > s ? '\u2713' : s}
              </div>
              <span className={cn(
                'text-[12px]',
                step === s ? 'text-[var(--text)]' : 'text-[var(--text-faint)]'
              )}>
                {s === 1 ? 'Task' : s === 2 ? 'Schedule' : 'Alerts'}
              </span>
              {s < 3 && <div className="w-8 h-px bg-[var(--hover-bg)]" />}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-6 py-6 space-y-5">
          {step === 1 && (
            <>
              {/* Task name */}
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Task Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Daily freshness check on orders"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  autoFocus
                />
              </div>

              {/* Mode toggle */}
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Task Type
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setTaskMode('prompt')}
                    className={cn(
                      'flex-1 flex items-center gap-2 p-3 rounded-lg transition-colors text-left',
                      taskMode === 'prompt'
                        ? 'bg-[var(--overlay-medium)] border border-[var(--overlay-strong)]'
                        : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                    )}
                  >
                    <svg className="w-5 h-5 text-[var(--text-tertiary)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                    <div>
                      <span className="text-[13px] font-medium text-[var(--text)] block">AI Prompt</span>
                      <span className="text-[11px] text-[var(--muted)]">Describe what to check in natural language</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTaskMode('structured')}
                    className={cn(
                      'flex-1 flex items-center gap-2 p-3 rounded-lg transition-colors text-left',
                      taskMode === 'structured'
                        ? 'bg-[var(--overlay-medium)] border border-[var(--overlay-strong)]'
                        : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                    )}
                  >
                    <svg className="w-5 h-5 text-[var(--text-tertiary)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <div>
                      <span className="text-[13px] font-medium text-[var(--text)] block">Structured Monitor</span>
                      <span className="text-[11px] text-[var(--muted)]">Configure specific check with thresholds</span>
                    </div>
                  </button>
                </div>
              </div>

              {/* Mode-specific content */}
              {taskMode === 'prompt' ? (
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Prompt
                  </label>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="e.g., Check if the orders table has received fresh data in the last 24 hours. If stale, report which datasets haven't been updated."
                    rows={4}
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2.5 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] resize-none"
                  />
                </div>
              ) : (
                <MonitorConfigForm
                  monitorType={monitorType}
                  onMonitorTypeChange={setMonitorType}
                  targetFqn={targetFqn}
                  onTargetFqnChange={setTargetFqn}
                  config={config}
                  onConfigChange={setConfig}
                  integrationId={integrationId}
                  groupedMonitors={groupedMonitors}
                />
              )}

              {/* Integration selection — dynamic based on monitor type */}
              {renderIntegrationSelector()}
            </>
          )}

          {step === 2 && (
            <>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Schedule
                </label>
                <ScheduleInput value={schedule} onChange={setSchedule} />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Timezone
                </label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
                >
                  <option value="UTC">UTC</option>
                  <option value="America/New_York">Eastern (ET)</option>
                  <option value="America/Chicago">Central (CT)</option>
                  <option value="America/Denver">Mountain (MT)</option>
                  <option value="America/Los_Angeles">Pacific (PT)</option>
                  <option value="Europe/London">London (GMT/BST)</option>
                  <option value="Europe/Berlin">Berlin (CET)</option>
                  <option value="Asia/Tokyo">Tokyo (JST)</option>
                </select>
              </div>
            </>
          )}

          {step === 3 && (
            <AlertChannelPicker
              channels={alertChannels}
              onChannelsChange={setAlertChannels}
              alertOnStatus={alertOnStatus}
              onAlertOnStatusChange={setAlertOnStatus}
              connectedChannels={connectedChannels}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 flex items-center justify-between px-6 py-4 border-t border-[var(--subtle-border)]">
          <div>
            {step > 1 && (
              <Button variant="ghost" size="sm" onClick={() => setStep(step - 1)}>
                Back
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            {step < 3 ? (
              <Button
                size="sm"
                onClick={() => setStep(step + 1)}
                disabled={step === 1 ? !canProceedStep1 : !canProceedStep2}
              >
                Next
              </Button>
            ) : (
              <Button size="sm" onClick={handleSubmit}>
                {isEditing ? 'Save Changes' : 'Create Task'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
