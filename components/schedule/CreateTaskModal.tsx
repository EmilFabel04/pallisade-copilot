'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import { MonitorConfigForm } from './MonitorConfigForm';

interface CreateTaskModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (task: any) => void;
  integrations?: Array<{ id: string; name: string; type: string }>;
}

export function CreateTaskModal({ open, onClose, onSubmit, integrations = [] }: CreateTaskModalProps) {
  const [step, setStep] = useState(1);

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

  if (!open) return null;

  const warehouseIntegrations = integrations.filter((i) =>
    ['bigquery', 'snowflake', 'postgres', 'redshift'].includes(i.type)
  );

  const isAnomalyNoColumn = ['ANOMALY', 'anomaly'].includes(monitorType)
    && (!config.metric || config.metric === 'row_count' || config.column === '*');
  const needsColumn = ['ANOMALY', 'anomaly', 'NULL_RATE', 'UNIQUENESS'].includes(monitorType)
    && !isAnomalyNoColumn;
  const canProceedStep1 = name.trim() && (
    taskMode === 'prompt'
      ? prompt.trim()
      : (monitorType && targetFqn.trim() && (!needsColumn || config.column?.trim()))
  );
  const canProceedStep2 = schedule.trim();

  const handleSubmit = () => {
    onSubmit({
      name,
      taskMode,
      prompt: taskMode === 'prompt' ? prompt : undefined,
      monitorType: taskMode === 'structured' ? monitorType : undefined,
      targetFqn: taskMode === 'structured' ? targetFqn : undefined,
      config: taskMode === 'structured' ? config : undefined,
      schedule,
      timezone,
      alertChannels,
      alertOnStatus,
      integrationId: integrationId || undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl mx-4 bg-[#0a0a12] rounded-2xl border border-white/[0.08] shadow-2xl max-h-[85vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <h2 className="text-[16px] font-semibold text-white">Create Scheduled Task</h2>
          <button onClick={onClose} className="text-white/40 hover:text-white">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Step indicators */}
        <div className="flex items-center gap-2 px-6 py-3 border-b border-white/[0.04]">
          {[1, 2, 3].map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div className={cn(
                'w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-medium',
                step === s
                  ? 'bg-white/[0.15] text-white'
                  : step > s
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-white/[0.04] text-white/30'
              )}>
                {step > s ? '✓' : s}
              </div>
              <span className={cn(
                'text-[12px]',
                step === s ? 'text-white' : 'text-white/30'
              )}>
                {s === 1 ? 'Task' : s === 2 ? 'Schedule' : 'Alerts'}
              </span>
              {s < 3 && <div className="w-8 h-px bg-white/[0.06]" />}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-5">
          {step === 1 && (
            <>
              {/* Task name */}
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Task Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Daily freshness check on orders"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                  autoFocus
                />
              </div>

              {/* Mode toggle */}
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Task Type
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setTaskMode('prompt')}
                    className={cn(
                      'flex-1 flex items-center gap-2 p-3 rounded-lg transition-colors text-left',
                      taskMode === 'prompt'
                        ? 'bg-white/[0.1] border border-white/[0.15]'
                        : 'bg-white/[0.03] border border-white/[0.06] hover:bg-white/[0.06]'
                    )}
                  >
                    <svg className="w-5 h-5 text-white/60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                    <div>
                      <span className="text-[13px] font-medium text-white block">AI Prompt</span>
                      <span className="text-[11px] text-white/40">Describe what to check in natural language</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTaskMode('structured')}
                    className={cn(
                      'flex-1 flex items-center gap-2 p-3 rounded-lg transition-colors text-left',
                      taskMode === 'structured'
                        ? 'bg-white/[0.1] border border-white/[0.15]'
                        : 'bg-white/[0.03] border border-white/[0.06] hover:bg-white/[0.06]'
                    )}
                  >
                    <svg className="w-5 h-5 text-white/60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <div>
                      <span className="text-[13px] font-medium text-white block">Structured Monitor</span>
                      <span className="text-[11px] text-white/40">Configure specific check with thresholds</span>
                    </div>
                  </button>
                </div>
              </div>

              {/* Mode-specific content */}
              {taskMode === 'prompt' ? (
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
                    Prompt
                  </label>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="e.g., Check if the orders table has received fresh data in the last 24 hours. If stale, report which datasets haven't been updated."
                    rows={4}
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2.5 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2] resize-none"
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
                />
              )}

              {/* Warehouse selection */}
              {warehouseIntegrations.length > 0 && (
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
                    Run against warehouse
                  </label>
                  <select
                    value={integrationId}
                    onChange={(e) => setIntegrationId(e.target.value)}
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white focus:outline-none focus:border-white/[0.2] appearance-none"
                  >
                    <option value="">Auto-detect</option>
                    {warehouseIntegrations.map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.name} ({i.type})
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </>
          )}

          {step === 2 && (
            <>
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Schedule
                </label>
                <ScheduleInput value={schedule} onChange={setSchedule} />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Timezone
                </label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white focus:outline-none focus:border-white/[0.2] appearance-none"
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
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-white/[0.06]">
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
                Create Task
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
