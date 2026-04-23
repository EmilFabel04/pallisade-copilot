'use client';

import React, { useState } from 'react';

type AudienceType = 'technical' | 'analyst' | 'executive' | 'stakeholder';

interface Explanation {
  summary: string;
  description: string;
  businessImpact: string;
  fixSteps: string[];
  priorityReason: string;
}

interface NLPExplanationProps {
  finding: {
    title: string;
    description: string;
    severity: string;
    category: string;
    table?: string;
    aiContext?: Record<string, any>;
  };
  explanations?: Record<AudienceType, Explanation>;
  defaultAudience?: AudienceType;
  className?: string;
}

// Fallback explanation generator when backend doesn't provide explanations
function generateFallbackExplanation(
  finding: NLPExplanationProps['finding'],
  audience: AudienceType
): Explanation {
  const severity = finding.severity || 'medium';
  const category = finding.category || 'quality';
  const table = finding.table || 'unknown table';

  const templates: Record<AudienceType, Explanation> = {
    technical: {
      summary: finding.title,
      description: finding.description || `Issue detected in ${table}`,
      businessImpact: 'May affect downstream data pipelines and reports',
      fixSteps: [
        '1. Investigate the root cause in the source system',
        '2. Check recent changes to the pipeline',
        '3. Review data quality tests',
        '4. Apply appropriate fix based on findings',
        '5. Verify fix and monitor for recurrence',
      ],
      priorityReason: severity === 'critical' 
        ? 'Critical severity: Immediate action required'
        : severity === 'high'
        ? 'High severity: Should be addressed within 4 hours'
        : 'Standard priority: Address within 24 hours',
    },
    analyst: {
      summary: `Data issue in ${table}`,
      description: finding.description || 'A data quality issue has been detected that may affect your analysis',
      businessImpact: 'Your analysis using this data may be inaccurate',
      fixSteps: [
        '1. Be aware of this issue when using this data',
        '2. Contact the data engineering team if needed',
        '3. Consider filtering or adjusting for the issue in your analysis',
      ],
      priorityReason: 'The data team is working on resolving this issue',
    },
    executive: {
      summary: `${severity.charAt(0).toUpperCase() + severity.slice(1)} data issue detected`,
      description: `A ${severity} priority data issue has been identified that may affect business reporting`,
      businessImpact: 'Business decisions may be affected if this issue persists',
      fixSteps: [
        '1. Data team has been alerted',
        '2. Resolution in progress',
        '3. Will provide update when resolved',
      ],
      priorityReason: severity === 'critical' 
        ? 'Highest priority: Business operations may be impacted'
        : 'Being addressed by the data team',
    },
    stakeholder: {
      summary: 'Data update in progress',
      description: 'We\'ve detected an issue with the data and are working to fix it',
      businessImpact: 'Your reports may show slightly different numbers until resolved',
      fixSteps: [
        '1. We\'re aware of the issue',
        '2. The team is working on it',
        '3. Should be resolved soon',
      ],
      priorityReason: 'Thank you for your patience',
    },
  };

  return templates[audience];
}

const audienceLabels: Record<AudienceType, { label: string; icon: React.ReactNode; color: string }> = {
  technical: {
    label: 'Technical',
    color: 'text-blue-400',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
      </svg>
    ),
  },
  analyst: {
    label: 'Analyst',
    color: 'text-purple-400',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
  },
  executive: {
    label: 'Executive',
    color: 'text-amber-400',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
  },
  stakeholder: {
    label: 'Stakeholder',
    color: 'text-green-400',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
      </svg>
    ),
  },
};

export function NLPExplanation({
  finding,
  explanations,
  defaultAudience = 'technical',
  className = '',
}: NLPExplanationProps) {
  const [audience, setAudience] = useState<AudienceType>(defaultAudience);
  const [copied, setCopied] = useState(false);

  const explanation = explanations?.[audience] || generateFallbackExplanation(finding, audience);

  const handleCopy = () => {
    const text = `
${explanation.summary}

${explanation.description}

Business Impact:
${explanation.businessImpact}

Fix Steps:
${explanation.fixSteps.join('\n')}
    `.trim();

    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`bg-[var(--card-bg)] rounded-lg border border-[var(--border-dim)] ${className}`}>
      {/* Header with audience selector */}
      <div className="px-4 py-3 border-b border-[var(--border-dim)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-[var(--accent)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          <span className="text-sm font-medium text-[var(--text)]">Explanation</span>
        </div>

        {/* Audience tabs */}
        <div className="flex items-center gap-1 bg-[var(--overlay-faint)] rounded-lg p-0.5">
          {(Object.keys(audienceLabels) as AudienceType[]).map((key) => (
            <button
              key={key}
              onClick={() => setAudience(key)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                audience === key
                  ? `bg-[var(--card-bg)] ${audienceLabels[key].color}`
                  : 'text-[var(--muted)] hover:text-[var(--text)]'
              }`}
              title={audienceLabels[key].label}
            >
              {audienceLabels[key].icon}
              <span className="hidden sm:inline">{audienceLabels[key].label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="p-4 space-y-4">
        {/* Summary */}
        <div>
          <h4 className="text-sm font-medium text-[var(--text)] mb-1">{explanation.summary}</h4>
          <p className="text-sm text-[var(--muted)]">{explanation.description}</p>
        </div>

        {/* Business Impact */}
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span className="text-xs font-medium text-amber-400 uppercase tracking-wider">Business Impact</span>
          </div>
          <p className="text-sm text-[var(--text)]">{explanation.businessImpact}</p>
        </div>

        {/* Fix Steps */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider">How to Fix</span>
            <button
              onClick={handleCopy}
              className="text-xs text-[var(--accent)] hover:text-[var(--text)] transition-colors flex items-center gap-1"
            >
              {copied ? (
                <>
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  Copied!
                </>
              ) : (
                <>
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                  </svg>
                  Copy
                </>
              )}
            </button>
          </div>
          <ol className="space-y-1.5">
            {explanation.fixSteps.map((step, i) => (
              <li key={i} className="text-sm text-[var(--muted)] pl-1">
                {step}
              </li>
            ))}
          </ol>
        </div>

        {/* Priority */}
        <div className="pt-3 border-t border-[var(--border-dim)]">
          <p className="text-xs text-[var(--muted)]">
            <span className="font-medium text-[var(--text)]">Priority: </span>
            {explanation.priorityReason}
          </p>
        </div>
      </div>
    </div>
  );
}

