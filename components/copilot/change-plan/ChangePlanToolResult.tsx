'use client';

import type {
  ValidationLevel,
  CreateChangePlanResult,
  ValidateChangePlanResult,
  ApplyChangePlanResult,
  ListChangePlansResult,
  GetChangePlanResult,
  ChangePlanStatus,
  ChangePlan,
} from '@/types/change-plan';
import { ChangePlanCard } from './ChangePlanCard';
import { ValidationStatus } from './ValidationStatus';
import { PRCard } from './PRCard';

type ShareTargetType = 'slack' | 'jira' | 'github_issue';

interface ChangePlanToolResultProps {
  toolName: string;
  result: CreateChangePlanResult | ValidateChangePlanResult | ApplyChangePlanResult | ListChangePlansResult | GetChangePlanResult;
  onValidate?: (planId: string, level: ValidationLevel) => void;
  onApply?: (planId: string) => void;
  onShare?: (planId: string, target: ShareTargetType) => void;
  onSaveToArtifacts?: (content: string) => void;
  associatedPlan?: ChangePlan;
  isApplying?: boolean;
}

const CHANGE_PLAN_TOOLS = [
  'create_change_plan',
  'validate_change_plan',
  'get_change_plan',
  'apply_change_plan',
  'list_change_plans',
];

export function isChangePlanTool(toolName: string): boolean {
  return CHANGE_PLAN_TOOLS.includes(toolName);
}

export function ChangePlanToolResult({ toolName, result, onValidate, onApply, onShare, onSaveToArtifacts, associatedPlan, isApplying }: ChangePlanToolResultProps) {
  // Guard against undefined/null result (can happen with streaming tool calls)
  if (!result) {
    return (
      <div
        className="rounded-lg p-3 text-sm"
        style={{
          backgroundColor: 'rgba(255, 255, 255, 0.03)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
        }}
      >
        <div className="flex items-center gap-2 text-white/50">
          <div className="w-3 h-3 border border-violet-400 border-t-transparent rounded-full animate-spin" />
          <span>Executing {toolName}...</span>
        </div>
      </div>
    );
  }

  // Handle error case
  if ('error' in result && result.error) {
    return (
      <div
        className="rounded-lg p-3 text-sm"
        style={{
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.2)',
        }}
      >
        <div className="flex items-center gap-2 text-red-400">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <span className="font-medium">Error</span>
        </div>
        <p className="mt-1 text-white/70">{result.error}</p>
      </div>
    );
  }

  // Handle success: false case
  if ('success' in result && !result.success) {
    return (
      <div
        className="rounded-lg p-3 text-sm"
        style={{
          backgroundColor: 'rgba(234, 179, 8, 0.1)',
          border: '1px solid rgba(234, 179, 8, 0.2)',
        }}
      >
        <div className="flex items-center gap-2 text-yellow-400">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
          <span className="font-medium">Operation failed</span>
        </div>
      </div>
    );
  }

  // Render based on tool name
  switch (toolName) {
    case 'create_change_plan': {
      const createResult = result as CreateChangePlanResult;
      if (createResult.plan) {
        return (
          <ChangePlanCard
            plan={createResult.plan}
            onValidate={onValidate}
            onApply={onApply}
            onShare={onShare}
            isApplying={isApplying}
          />
        );
      }
      // Fallback: show summary if no full plan
      return (
        <div
          className="rounded-lg p-3"
          style={{
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            border: '1px solid rgba(16, 185, 129, 0.2)',
          }}
        >
          <div className="flex items-center gap-2 text-emerald-400 mb-2">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
              />
            </svg>
            <span className="font-medium">Change Plan Created</span>
          </div>
          <div className="text-sm text-white/70 space-y-1">
            <div><span className="text-white/50">ID:</span> <span className="font-mono">{createResult.plan_id}</span></div>
            {createResult.title && <div><span className="text-white/50">Title:</span> {createResult.title}</div>}
            {createResult.patches_count !== undefined && (
              <div><span className="text-white/50">Files:</span> {createResult.patches_count}</div>
            )}
          </div>
        </div>
      );
    }

    case 'validate_change_plan': {
      const validateResult = result as ValidateChangePlanResult;
      return (
        <div
          className="rounded-lg p-3"
          style={{
            backgroundColor: validateResult.status === 'passed'
              ? 'rgba(16, 185, 129, 0.1)'
              : validateResult.status === 'failed'
                ? 'rgba(239, 68, 68, 0.1)'
                : 'rgba(234, 179, 8, 0.1)',
            border: `1px solid ${
              validateResult.status === 'passed'
                ? 'rgba(16, 185, 129, 0.2)'
                : validateResult.status === 'failed'
                  ? 'rgba(239, 68, 68, 0.2)'
                  : 'rgba(234, 179, 8, 0.2)'
            }`,
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            {validateResult.status === 'passed' ? (
              <svg className="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : validateResult.status === 'failed' ? (
              <svg className="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            )}
            <span
              className={`font-medium ${
                validateResult.status === 'passed'
                  ? 'text-emerald-400'
                  : validateResult.status === 'failed'
                    ? 'text-red-400'
                    : 'text-yellow-400'
              }`}
            >
              {validateResult.level?.toUpperCase()} Validation: {validateResult.status?.toUpperCase()}
            </span>
          </div>

          {validateResult.errors && validateResult.errors.length > 0 && (
            <div className="mb-2">
              <span className="text-xs text-red-400 font-medium">Errors:</span>
              <ul className="text-sm text-white/70 mt-1 space-y-0.5">
                {validateResult.errors.map((err, i) => (
                  <li key={i} className="pl-2 border-l-2 border-red-400/30">{err}</li>
                ))}
              </ul>
            </div>
          )}

          {validateResult.warnings && validateResult.warnings.length > 0 && (
            <div>
              <span className="text-xs text-yellow-400 font-medium">Warnings:</span>
              <ul className="text-sm text-white/70 mt-1 space-y-0.5">
                {validateResult.warnings.map((warn, i) => (
                  <li key={i} className="pl-2 border-l-2 border-yellow-400/30">{warn}</li>
                ))}
              </ul>
            </div>
          )}

          {validateResult.is_validated && (
            <div className="mt-2 text-sm text-emerald-400">
              Plan is ready to apply
            </div>
          )}
        </div>
      );
    }

    case 'get_change_plan': {
      const getResult = result as GetChangePlanResult;
      if (getResult.plan) {
        return (
          <ChangePlanCard
            plan={getResult.plan}
            onValidate={onValidate}
            onApply={onApply}
            onShare={onShare}
            isApplying={isApplying}
          />
        );
      }
      return null;
    }

    case 'apply_change_plan': {
      const applyResult = result as ApplyChangePlanResult;
      return (
        <PRCard
          result={applyResult}
          plan={associatedPlan}
          onSaveToArtifacts={onSaveToArtifacts}
        />
      );
    }

    case 'list_change_plans': {
      const listResult = result as ListChangePlansResult;
      if (!listResult.plans || listResult.plans.length === 0) {
        return (
          <div
            className="rounded-lg p-3 text-sm text-white/60"
            style={{
              backgroundColor: 'rgba(255, 255, 255, 0.02)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
            }}
          >
            No change plans in this session
          </div>
        );
      }

      return (
        <div className="space-y-2">
          <div className="text-xs text-white/50">{listResult.count} change plan{listResult.count !== 1 ? 's' : ''}</div>
          {listResult.plans.map((plan) => (
            <div
              key={plan.id}
              className="flex items-center justify-between p-3 rounded-lg"
              style={{
                backgroundColor: 'rgba(255, 255, 255, 0.02)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
              }}
            >
              <div className="min-w-0">
                <div className="text-sm font-medium text-white/90 truncate">{plan.title}</div>
                <div className="text-xs text-white/50 font-mono">{plan.id}</div>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                  style={{
                    backgroundColor:
                      plan.status === 'validated' || plan.status === 'applied'
                        ? 'rgba(16, 185, 129, 0.2)'
                        : plan.status === 'failed'
                          ? 'rgba(239, 68, 68, 0.2)'
                          : 'rgba(156, 163, 175, 0.2)',
                    color:
                      plan.status === 'validated' || plan.status === 'applied'
                        ? '#34d399'
                        : plan.status === 'failed'
                          ? '#f87171'
                          : '#9ca3af',
                  }}
                >
                  {plan.status}
                </span>
                {plan.pr_url && (
                  <a
                    href={plan.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline text-xs"
                  >
                    PR
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      );
    }

    default:
      return null;
  }
}
