'use client';

import { useState } from 'react';
import { 
  CheckCircle, 
  XCircle, 
  AlertTriangle, 
  HelpCircle,
  Lightbulb,
  GitBranch,
  Layers,
  RefreshCw
} from 'lucide-react';

interface DetectedPattern {
  type: string;
  explanation: string;
  correlates_with?: string;
  confidence: number;
  group_stats?: {
    total_pairs?: number;
    unique_pairs?: number;
    uniqueness_ratio?: number;
  };
}

interface PatternFinding {
  id?: string;
  table: string;
  column?: string;
  dataset?: string;  // For multi-dataset scans
  title: string;
  description: string;
  severity: string;
  needs_confirmation?: boolean;
  detected_pattern?: DetectedPattern;
  suggested_rule?: {
    name: string;
    table_pattern: string;
    column_pattern: string;
    finding_type: string;
    pattern_type: string;
    detection_confidence: number;
    context: {
      explanation: string;
      correlates_with?: string;
    };
  };
  ai_context?: {
    pattern_analysis?: {
      pattern_detected: boolean;
      pattern_type?: string;
      confidence: number;
      correlates_with?: string;
    };
    confirmation_prompt?: string;
    possible_actions?: Array<{
      action: string;
      description: string;
    }>;
  };
}

interface PatternConfirmationProps {
  findings: PatternFinding[];
  onConfirm: (finding: PatternFinding) => Promise<void>;
  onReject: (finding: PatternFinding, reason?: string) => Promise<void>;
  onRefresh?: () => void;
}

const PATTERN_ICONS: Record<string, React.ReactNode> = {
  column_correlation: <GitBranch className="w-4 h-4" />,
  foreign_key: <Layers className="w-4 h-4" />,
  time_snapshot: <RefreshCw className="w-4 h-4" />,
  scd_versioning: <Layers className="w-4 h-4" />,
  expected_null: <HelpCircle className="w-4 h-4" />,
  expected_outlier: <AlertTriangle className="w-4 h-4" />,
};

const PATTERN_LABELS: Record<string, string> = {
  column_correlation: 'Column Correlation',
  foreign_key: 'Foreign Key',
  time_snapshot: 'Time Snapshot',
  scd_versioning: 'SCD Versioning',
  expected_null: 'Expected Nulls',
  expected_outlier: 'Expected Outliers',
  grouping_key: 'Grouping Key',
};

export function PatternConfirmationCard({ 
  finding,
  onConfirm,
  onReject,
  isProcessing
}: { 
  finding: PatternFinding;
  onConfirm: () => void;
  onReject: (reason?: string) => void;
  isProcessing: boolean;
}) {
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  
  const pattern = finding.detected_pattern;
  const patternType = pattern?.type || 'unknown';
  const confidence = pattern?.confidence || 0;
  const confidencePercent = Math.round(confidence * 100);
  
  return (
    <div className="dashboard-card overflow-hidden border-l-4 border-amber-500/50">
      {/* Header */}
      <div className="p-4 bg-amber-500/5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-500/20 flex items-center justify-center flex-shrink-0">
              <Lightbulb className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-semibold text-[15px]">{finding.title}</h3>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-500/20 text-amber-400">
                  Needs Review
                </span>
              </div>
              <p className="text-sm text-[var(--muted)]">
                {finding.description}
              </p>
            </div>
          </div>
        </div>
      </div>
      
      {/* Pattern Details */}
      <div className="p-4 space-y-4">
        {/* Pattern Type & Confidence */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--subtle-bg)]">
            <span className="text-amber-400">
              {PATTERN_ICONS[patternType] || <HelpCircle className="w-4 h-4" />}
            </span>
            <span className="text-sm font-medium">
              {PATTERN_LABELS[patternType] || patternType}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--muted)]">Confidence:</span>
            <div className="w-24 h-2 bg-[var(--overlay-medium)] rounded-full overflow-hidden">
              <div 
                className={`h-full transition-all ${
                  confidencePercent >= 80 ? 'bg-emerald-500' : 
                  confidencePercent >= 60 ? 'bg-amber-500' : 'bg-red-500'
                }`}
                style={{ width: `${confidencePercent}%` }}
              />
            </div>
            <span className={`text-xs font-medium ${
              confidencePercent >= 80 ? 'text-emerald-400' : 
              confidencePercent >= 60 ? 'text-amber-400' : 'text-red-400'
            }`}>
              {confidencePercent}%
            </span>
          </div>
        </div>
        
        {/* Explanation */}
        <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
          <div className="text-xs text-[var(--muted)] uppercase tracking-wider mb-1">Pattern Detected</div>
          <p className="text-sm">{pattern?.explanation || 'Pattern analysis detected a potential expected behavior.'}</p>
          
          {pattern?.correlates_with && (
            <div className="mt-2 flex items-center gap-2 text-sm">
              <span className="text-[var(--muted)]">Correlates with:</span>
              <code className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono text-xs">
                {pattern.correlates_with}
              </code>
            </div>
          )}
          
          {pattern?.group_stats && (
            <div className="mt-2 flex items-center gap-4 text-xs text-[var(--muted)]">
              {pattern.group_stats.total_pairs && (
                <span>Total pairs: {pattern.group_stats.total_pairs.toLocaleString()}</span>
              )}
              {pattern.group_stats.uniqueness_ratio && (
                <span>Uniqueness: {(pattern.group_stats.uniqueness_ratio * 100).toFixed(1)}%</span>
              )}
            </div>
          )}
        </div>
        
        {/* Location */}
        <div className="flex items-center gap-4 text-sm flex-wrap">
          {finding.dataset && (
            <div className="flex items-center gap-2">
              <span className="text-[var(--muted)]">Dataset:</span>
              <code className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 font-mono text-xs">
                {finding.dataset}
              </code>
            </div>
          )}
          <div className="flex items-center gap-2">
            <span className="text-[var(--muted)]">Table:</span>
            <code className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 font-mono text-xs">
              {finding.table}
            </code>
          </div>
          {finding.column && (
            <div className="flex items-center gap-2">
              <span className="text-[var(--muted)]">Column:</span>
              <code className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono text-xs">
                {finding.column}
              </code>
            </div>
          )}
        </div>
        
        {/* AI Prompt */}
        {finding.ai_context?.confirmation_prompt && (
          <div className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
            <p className="text-sm text-blue-300">
              {finding.ai_context.confirmation_prompt}
            </p>
          </div>
        )}
        
        {/* Actions */}
        {!showRejectInput ? (
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={onConfirm}
              disabled={isProcessing}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm"
            >
              <CheckCircle className="w-4 h-4" />
              Yes, this is expected
            </button>
            <button
              onClick={() => setShowRejectInput(true)}
              disabled={isProcessing}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm"
            >
              <XCircle className="w-4 h-4" />
              No, flag as issue
            </button>
          </div>
        ) : (
          <div className="space-y-3 pt-2">
            <div>
              <label className="text-xs text-[var(--muted)] uppercase tracking-wider mb-1 block">
                Why is this a real issue? (optional)
              </label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Help us improve: explain why this pattern is actually a problem..."
                className="w-full px-3 py-2 rounded-lg bg-[var(--overlay-bg)] border border-[var(--border-medium)] focus:border-red-500/50 focus:outline-none text-sm resize-none"
                rows={2}
              />
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => {
                  onReject(rejectReason || undefined);
                  setShowRejectInput(false);
                  setRejectReason('');
                }}
                disabled={isProcessing}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-red-500 text-white hover:bg-red-600 transition-all disabled:opacity-50 font-medium text-sm"
              >
                <XCircle className="w-4 h-4" />
                Flag as Issue
              </button>
              <button
                onClick={() => {
                  setShowRejectInput(false);
                  setRejectReason('');
                }}
                className="px-4 py-2 rounded-lg bg-[var(--subtle-bg)] hover:bg-[var(--overlay-medium)] transition-all text-sm"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Generate a unique ID for a finding based on its content
function generateFindingId(finding: PatternFinding, index: number): string {
  // Use multiple fields to create a unique identifier
  const parts = [
    finding.id,
    finding.table,
    finding.column,
    finding.title?.slice(0, 50),
    finding.detected_pattern?.type,
    index.toString(),
  ].filter(Boolean);
  return parts.join('-');
}

export function PatternConfirmationPanel({
  findings,
  onConfirm,
  onReject,
  onRefresh
}: PatternConfirmationProps) {
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [confirmedIds, setConfirmedIds] = useState<Set<string>>(new Set());
  const [rejectedIds, setRejectedIds] = useState<Set<string>>(new Set());
  
  // Filter to only show findings that need confirmation and haven't been processed
  // Use index to generate unique IDs, sorted by severity (critical first)
  const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
  const pendingFindings = findings
    .map((f, idx) => ({ ...f, _uniqueId: generateFindingId(f, idx) }))
    .filter(f => 
      f.needs_confirmation && 
      !confirmedIds.has(f._uniqueId) &&
      !rejectedIds.has(f._uniqueId)
    )
    .sort((a, b) => (severityOrder[a.severity] ?? 5) - (severityOrder[b.severity] ?? 5));
  
  if (pendingFindings.length === 0) {
    return null;
  }
  
  const handleConfirm = async (finding: PatternFinding & { _uniqueId: string }) => {
    const id = finding._uniqueId;
    setProcessingId(id);
    try {
      await onConfirm(finding);
      setConfirmedIds(prev => new Set([...prev, id]));
    } catch (error) {
      console.error('Failed to confirm pattern:', error);
    } finally {
      setProcessingId(null);
    }
  };
  
  const handleReject = async (finding: PatternFinding & { _uniqueId: string }, reason?: string) => {
    const id = finding._uniqueId;
    setProcessingId(id);
    try {
      await onReject(finding, reason);
      setRejectedIds(prev => new Set([...prev, id]));
    } catch (error) {
      console.error('Failed to reject pattern:', error);
    } finally {
      setProcessingId(null);
    }
  };
  
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center">
            <Lightbulb className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Patterns Detected</h2>
            <p className="text-sm text-[var(--muted)]">
              The scanner found {pendingFindings.length} potential pattern{pendingFindings.length !== 1 ? 's' : ''} that may be expected behavior
            </p>
          </div>
        </div>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="p-2 rounded-lg hover:bg-[var(--subtle-bg)] transition-colors"
          >
            <RefreshCw className="w-4 h-4 text-[var(--muted)]" />
          </button>
        )}
      </div>
      
      {/* Info Banner */}
      <div className="p-4 rounded-xl bg-blue-500/5 border border-blue-500/20">
        <div className="flex items-start gap-3">
          <HelpCircle className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm text-blue-300/90">
            <p className="font-medium mb-1">How does this work?</p>
            <p className="text-blue-300/70">
              When you confirm a pattern, the scanner will remember it and won&apos;t flag similar findings in future scans. 
              If you reject it, it will be treated as a real issue that needs to be fixed.
            </p>
          </div>
        </div>
      </div>
      
      {/* Pattern Cards */}
      <div className="space-y-4">
        {pendingFindings.map((finding) => (
          <PatternConfirmationCard
            key={finding._uniqueId}
            finding={finding}
            onConfirm={() => handleConfirm(finding)}
            onReject={(reason) => handleReject(finding, reason)}
            isProcessing={processingId === finding._uniqueId}
          />
        ))}
      </div>
    </div>
  );
}

export default PatternConfirmationPanel;
