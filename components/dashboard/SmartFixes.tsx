'use client';

import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { useRouter } from 'next/navigation';
import { ApplyFixModal } from './ApplyFixModal';
import { useFixTest } from './FixTestContext';

interface Fix {
  id: string;
  title: string;
  description: string;
  stack: string;
  language: string;
  confidence: 'high' | 'medium' | 'low';
  confidenceScore?: number; // 0.0 - 1.0 from learning system
  effort: 'instant' | 'minutes' | 'hours' | 'days';
  code: string;
  file_path?: string;
  why: string;
  priority: number;
  
  // Learning system fields
  source?: 'template' | 'rag' | 'learned';
  similarFixesCount?: number;
  similarFixesSuccessRate?: number;
  reasoning?: string;
}

interface Finding {
  id: string;
  type?: string;
  category?: string;
  severity?: string;
  title?: string;
  description?: string;
  table?: string;
  column?: string;
  scan_type?: string;
  ai_context?: Record<string, unknown>;
}

interface FixResult {
  finding_id: string;
  finding_title: string;
  finding_severity?: string;
  finding_table?: string;
  fixes: Fix[];
}

interface SmartFixesProps {
  fixes?: Fix[];
  finding?: Finding; // For fetching recommendations
  findingTitle?: string;
  findingId?: string;
  reportId?: string;
  table?: string;
  column?: string;
  compact?: boolean;
  autoFetchRecommendations?: boolean;
}

const STACK_ICONS: Record<string, string> = {
  dbt: '🔧',
  snowflake: '❄️',
  bigquery: '🔷',
  redshift: '🔴',
  airflow: '🌀',
  python: '🐍',
  sql: '📝',
};

const CONFIDENCE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  high: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', label: 'High confidence' },
  medium: { bg: 'bg-amber-500/10', text: 'text-amber-400', label: 'Medium confidence' },
  low: { bg: 'bg-red-500/10', text: 'text-red-400', label: 'Needs review' },
};

const EFFORT_LABELS: Record<string, string> = {
  instant: '⚡ Copy & paste',
  minutes: '⏱️ 5-15 min',
  hours: '🕐 1-4 hours',
  days: '📅 Days',
};

const SOURCE_BADGES: Record<string, { bg: string; text: string; label: string }> = {
  template: { bg: 'bg-blue-500/10', text: 'text-blue-400', label: 'Template' },
  rag: { bg: 'bg-purple-500/10', text: 'text-purple-400', label: 'Similar fixes' },
  learned: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', label: 'Learned' },
};

// Check if a fix can be auto-applied
const canAutoApply = (fix: Fix): boolean => {
  return (
    fix.stack === 'dbt' || 
    fix.language === 'yaml' ||
    fix.language === 'sql' ||
    fix.language === 'python'
  );
};

// Convert confidence score to label
const getConfidenceLabel = (score?: number): 'high' | 'medium' | 'low' => {
  if (!score) return 'medium';
  if (score >= 0.8) return 'high';
  if (score >= 0.6) return 'medium';
  return 'low';
};

export function SmartFixes({ 
  fixes: initialFixes,
  finding,
  findingTitle, 
  findingId,
  reportId,
  table,
  column,
  compact = false,
  autoFetchRecommendations = false,
}: SmartFixesProps) {
  const router = useRouter();
  const { navigateToSandbox, setFixToTest } = useFixTest();
  
  const [fixes, setFixes] = useState<Fix[]>(initialFixes || []);
  const [expandedFix, setExpandedFix] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [applyModalOpen, setApplyModalOpen] = useState(false);
  const [selectedFix, setSelectedFix] = useState<Fix | null>(null);
  const [loading, setLoading] = useState(false);
  const [learningStats, setLearningStats] = useState<{
    successRate?: number;
    totalFixes?: number;
  } | null>(null);

  // Fetch recommendations from learning system
  useEffect(() => {
    if (autoFetchRecommendations && finding && fixes.length === 0) {
      fetchRecommendations();
    }
  }, [finding, autoFetchRecommendations]);

  // Set first fix as expanded
  useEffect(() => {
    if (fixes.length > 0 && !expandedFix) {
      setExpandedFix(fixes[0].id);
    }
  }, [fixes]);

  const fetchRecommendations = async () => {
    if (!finding) return;
    
    setLoading(true);
    try {
      const response = await fetch('/api/fixes/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          finding: {
            id: finding.id,
            type: finding.type,
            category: finding.category,
            severity: finding.severity,
            title: finding.title || findingTitle,
            description: finding.description,
            table: finding.table || table,
            column: finding.column || column,
            scan_type: finding.scan_type,
            ai_context: finding.ai_context,
          },
          max_recommendations: 5,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        
        // Convert recommendations to Fix format
        const newFixes: Fix[] = (data.recommendations || []).map((rec: any, index: number) => ({
          id: rec.recommendation_id || `fix-${index}`,
          title: rec.fix_type?.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()) || 'Fix',
          description: rec.reasoning?.split('.')[0] || 'Apply this fix to resolve the issue',
          stack: rec.fix_type?.includes('dbt') ? 'dbt' : 
                 rec.fix_type?.includes('airflow') ? 'airflow' :
                 rec.fix_type?.includes('sql') ? 'sql' : 'dbt',
          language: rec.fix_language || 'yaml',
          confidence: getConfidenceLabel(rec.confidence_score),
          confidenceScore: rec.confidence_score,
          effort: 'minutes' as const,
          code: rec.fix_template,
          file_path: rec.file_path,
          why: rec.reasoning || 'This fix addresses the detected issue.',
          priority: index + 1,
          source: rec.source,
          similarFixesCount: rec.similar_fixes_count,
          similarFixesSuccessRate: rec.similar_fixes_success_rate,
          reasoning: rec.reasoning,
        }));

        setFixes(newFixes);
        
        // Store learning stats
        if (data.statistics) {
          setLearningStats({
            successRate: data.statistics.success_rate,
            totalFixes: data.statistics.total,
          });
        }
      }
    } catch (error) {
      console.error('Failed to fetch recommendations:', error);
    } finally {
      setLoading(false);
    }
  };

  const copyCode = async (code: string, fixId: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedId(fixId);
      toast.success('Code copied to clipboard!');
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      toast.error('Failed to copy');
    }
  };

  const handleApplyClick = (fix: Fix) => {
    setSelectedFix({
      ...fix,
      stack_component: fix.stack,
    } as any);
    setApplyModalOpen(true);
  };

  const handleTestClick = (fix: Fix) => {
    // Set fix context and navigate to Sandbox Lab
    setFixToTest({
      id: fix.id,
      title: fix.title,
      description: fix.description,
      code: fix.code,
      language: fix.language,
      stack: fix.stack,
      confidence: fix.confidence,
      confidenceScore: fix.confidenceScore,
      file_path: fix.file_path,
      why: fix.why,
      findingId,
      findingTitle,
      findingSeverity: finding?.severity,
      reportId,
      table: finding?.table || table,
      column: finding?.column || column,
      issueType: finding?.type || finding?.scan_type,
      issueCategory: finding?.category,
      metricsSnapshot: finding?.ai_context ? {
        null_rate: finding.ai_context.null_rate as number | undefined,
        freshness_hours: (finding.ai_context.hours_stale || finding.ai_context.freshness_hours) as number | undefined,
        row_count: finding.ai_context.row_count as number | undefined,
      } : undefined,
      sourceDialect: fix.stack === 'snowflake' ? 'snowflake' : 
                     fix.stack === 'bigquery' ? 'bigquery' : 
                     fix.stack === 'redshift' ? 'redshift' : 'snowflake',
      generationMethod: fix.source || 'template',
    });
    
    // Navigate to Sandbox Lab
    router.push('/dashboard/sandbox');
    toast.info('Opening Sandbox Lab to test fix...');
  };

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-4">
        <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
        <span className="text-sm text-[var(--muted)]">Generating smart fixes...</span>
      </div>
    );
  }

  if (fixes.length === 0) {
    return (
      <div className="text-sm text-[var(--muted)] italic">
        {autoFetchRecommendations ? (
          <button
            onClick={fetchRecommendations}
            className="text-[var(--accent)] hover:underline"
          >
            Generate smart fixes →
          </button>
        ) : (
          'No auto-fixes available for this finding.'
        )}
      </div>
    );
  }

  if (compact) {
    // Compact view - just show the best fix
    const bestFix = fixes[0];
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span>{STACK_ICONS[bestFix.stack] || '🔧'}</span>
            <span className="text-sm font-medium">{bestFix.title}</span>
            {bestFix.confidenceScore && (
              <span className={`text-xs px-2 py-0.5 rounded-full ${CONFIDENCE_STYLES[bestFix.confidence].bg} ${CONFIDENCE_STYLES[bestFix.confidence].text}`}>
                {Math.round(bestFix.confidenceScore * 100)}%
              </span>
            )}
            {bestFix.source && SOURCE_BADGES[bestFix.source] && (
              <span className={`text-xs px-2 py-0.5 rounded-full ${SOURCE_BADGES[bestFix.source].bg} ${SOURCE_BADGES[bestFix.source].text}`}>
                {SOURCE_BADGES[bestFix.source].label}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleTestClick(bestFix)}
              className="text-xs px-3 py-1 rounded bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 transition-colors flex items-center gap-1"
            >
              🧪 Test in Sandbox
            </button>
            {canAutoApply(bestFix) && (
              <button
                onClick={() => handleApplyClick(bestFix)}
                className="text-xs px-3 py-1 rounded bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 transition-colors"
              >
                🚀 Apply
              </button>
            )}
            <button
              onClick={() => copyCode(bestFix.code, bestFix.id)}
              className="text-xs px-3 py-1 rounded bg-[var(--accent)] hover:bg-[var(--accent-2)] transition-colors"
            >
              {copiedId === bestFix.id ? '✓ Copied' : '📋 Copy'}
            </button>
          </div>
        </div>
        <pre className="text-xs bg-[var(--overlay-bg)] p-3 rounded-lg overflow-x-auto max-h-32">
          <code>{bestFix.code.slice(0, 300)}{bestFix.code.length > 300 ? '...' : ''}</code>
        </pre>
        
        {/* Learning indicator */}
        {bestFix.similarFixesCount && bestFix.similarFixesCount > 0 && (
          <div className="text-xs text-[var(--muted)] flex items-center gap-2">
            <span>📊</span>
            <span>
              Based on {bestFix.similarFixesCount} similar fixes 
              ({Math.round((bestFix.similarFixesSuccessRate || 0) * 100)}% success rate)
            </span>
          </div>
        )}
        
        {/* Apply Fix Modal */}
        {selectedFix && (
          <ApplyFixModal
            isOpen={applyModalOpen}
            onClose={() => setApplyModalOpen(false)}
            fix={selectedFix as any}
            findingTitle={findingTitle}
            findingId={findingId}
            reportId={reportId}
            table={table}
          />
        )}
      </div>
    );
  }

  // Full view with all fixes
  return (
    <div className="space-y-3">
      {findingTitle && (
        <div className="text-sm text-[var(--muted)]">
          Fixes for: <span className="text-[var(--text)]">{findingTitle}</span>
        </div>
      )}

      {/* Learning stats banner */}
      {learningStats && learningStats.totalFixes && learningStats.totalFixes > 0 && (
        <div className="p-3 rounded-xl bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/20 flex items-center gap-3">
          <span className="text-lg">🧠</span>
          <div className="flex-1">
            <div className="text-sm font-medium">Learning-Enhanced Recommendations</div>
            <div className="text-xs text-[var(--muted)]">
              Based on {learningStats.totalFixes} past fixes • 
              {Math.round((learningStats.successRate || 0) * 100)}% overall success rate
            </div>
          </div>
        </div>
      )}

      {fixes.map((fix, index) => {
        const isExpanded = expandedFix === fix.id;
        const confidenceStyle = CONFIDENCE_STYLES[fix.confidence];
        const showApply = canAutoApply(fix);
        
        return (
          <div
            key={fix.id}
            className={`border rounded-xl overflow-hidden transition-all ${
              isExpanded 
                ? 'border-[var(--accent)]/30 bg-[rgba(139,11,16,0.05)]' 
                : 'border-[var(--subtle-border)] hover:border-[var(--overlay-strong)]'
            }`}
          >
            {/* Fix Header */}
            <button
              onClick={() => setExpandedFix(isExpanded ? null : fix.id)}
              className="w-full p-4 flex items-center gap-3 text-left"
            >
              {/* Priority badge */}
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-lg ${
                index === 0 ? 'bg-[var(--accent)]/20' : 'bg-[var(--subtle-bg)]'
              }`}>
                {STACK_ICONS[fix.stack] || '🔧'}
              </div>
              
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium">{fix.title}</span>
                  {index === 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--accent)]/20 text-[var(--accent-2)]">
                      Recommended
                    </span>
                  )}
                  {/* Confidence with percentage */}
                  <span className={`text-xs px-2 py-0.5 rounded-full ${confidenceStyle.bg} ${confidenceStyle.text}`}>
                    {fix.confidenceScore 
                      ? `${Math.round(fix.confidenceScore * 100)}%` 
                      : confidenceStyle.label}
                  </span>
                  {/* Source badge */}
                  {fix.source && SOURCE_BADGES[fix.source] && (
                    <span className={`text-xs px-2 py-0.5 rounded-full ${SOURCE_BADGES[fix.source].bg} ${SOURCE_BADGES[fix.source].text}`}>
                      {SOURCE_BADGES[fix.source].label}
                    </span>
                  )}
                  {showApply && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400">
                      One-click apply
                    </span>
                  )}
                </div>
                <div className="text-sm text-[var(--muted)] mt-0.5">
                  {fix.description}
                </div>
              </div>
              
              <div className="flex items-center gap-3">
                <span className="text-xs text-[var(--muted)]">{EFFORT_LABELS[fix.effort]}</span>
                <svg 
                  className={`w-5 h-5 text-[var(--muted)] transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none" 
                  stroke="currentColor" 
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </button>

            {/* Expanded Content */}
            {isExpanded && (
              <div className="px-4 pb-4 space-y-4 border-t border-[var(--border-faint)]">
                {/* Why this fix + Learning data */}
                <div className="pt-4">
                  <div className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-2">
                    Why this fix?
                  </div>
                  <p className="text-sm">{fix.why}</p>
                  
                  {/* Learning evidence */}
                  {fix.similarFixesCount && fix.similarFixesCount > 0 && (
                    <div className="mt-3 p-3 rounded-lg bg-[var(--overlay-faint)] border border-[var(--border-dim)]">
                      <div className="flex items-center gap-3 text-sm">
                        <div className="flex items-center gap-1.5">
                          <span className="text-purple-400">📊</span>
                          <span className="text-[var(--muted)]">Similar fixes:</span>
                          <span className="font-medium">{fix.similarFixesCount}</span>
                        </div>
                        <div className="w-px h-4 bg-[var(--border-dim)]" />
                        <div className="flex items-center gap-1.5">
                          <span className="text-emerald-400">✓</span>
                          <span className="text-[var(--muted)]">Success rate:</span>
                          <span className="font-medium text-emerald-400">
                            {Math.round((fix.similarFixesSuccessRate || 0) * 100)}%
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* File path */}
                {fix.file_path && (
                  <div>
                    <div className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-1">
                      Add to file
                    </div>
                    <code className="text-sm text-blue-400">{fix.file_path}</code>
                  </div>
                )}

                {/* Code */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide">
                      Code ({fix.language})
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Test in Sandbox Button */}
                      <button
                        onClick={() => handleTestClick(fix)}
                        className="text-xs px-3 py-1.5 rounded-lg transition-all bg-gradient-to-r from-blue-600/30 to-cyan-600/30 text-cyan-400 hover:from-blue-600/40 hover:to-cyan-600/40 flex items-center gap-1.5 border border-cyan-500/30"
                      >
                        🧪 Test in Sandbox
                      </button>
                      {showApply && (
                        <button
                          onClick={() => handleApplyClick(fix)}
                          className={`text-xs px-3 py-1.5 rounded-lg transition-all bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 flex items-center gap-1.5`}
                        >
                          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                          </svg>
                          Apply to GitHub
                        </button>
                      )}
                      <button
                        onClick={() => copyCode(fix.code, fix.id)}
                        className={`text-xs px-3 py-1.5 rounded-lg transition-all ${
                          copiedId === fix.id
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : 'bg-[var(--subtle-bg)] hover:bg-[var(--overlay-medium)]'
                        }`}
                      >
                        {copiedId === fix.id ? '✓ Copied!' : '📋 Copy Code'}
                      </button>
                    </div>
                  </div>
                  <pre className="text-sm bg-[var(--overlay-bg)] p-4 rounded-xl overflow-x-auto">
                    <code className={`language-${fix.language}`}>{fix.code}</code>
                  </pre>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {fixes.length > 1 && (
        <div className="text-xs text-[var(--muted)] text-center pt-2">
          {fixes.length} fixes available • Ordered by confidence and stack relevance
        </div>
      )}

      {/* Apply Fix Modal */}
      {selectedFix && (
        <ApplyFixModal
          isOpen={applyModalOpen}
          onClose={() => setApplyModalOpen(false)}
          fix={selectedFix as any}
          findingTitle={findingTitle}
          findingId={findingId}
          reportId={reportId}
          table={table}
        />
      )}
    </div>
  );
}

// Panel component for the report detail page
export function SmartFixesPanel({ reportId }: { reportId: string }) {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<FixResult[]>([]);
  const [stack, setStack] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const loadFixes = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const res = await fetch(`/api/fixes?reportId=${reportId}`);
      const data = await res.json();
      
      if (data.success) {
        setResults(data.results);
        setStack(data.stack);
        setLoaded(true);
      } else {
        setError(data.error || 'Failed to load fixes');
      }
    } catch (err) {
      setError('Failed to load fixes');
    } finally {
      setLoading(false);
    }
  };

  if (!loaded) {
    return (
      <div className="dashboard-card p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold flex items-center gap-2">
              🔧 Smart Auto-Fixes
              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400">
                AI + Learning
              </span>
            </h3>
            <p className="text-sm text-[var(--muted)]">AI-generated fixes that improve with your feedback</p>
          </div>
          <button
            onClick={loadFixes}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] transition-colors disabled:opacity-50"
          >
            {loading ? 'Loading...' : 'Generate Fixes'}
          </button>
        </div>
        
        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 text-red-400 text-sm">
            {error}
          </div>
        )}
      </div>
    );
  }

  const totalFixes = results.reduce((acc, r) => acc + r.fixes.length, 0);
  const applyableFixes = results.reduce((acc, r) => 
    acc + r.fixes.filter(f => canAutoApply(f)).length, 0
  );

  return (
    <div className="space-y-6">
      {/* Header Card */}
      <div className="dashboard-card p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-semibold flex items-center gap-2 text-lg">
              🔧 Smart Auto-Fixes
              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400">
                AI + Learning
              </span>
            </h3>
            <p className="text-sm text-[var(--muted)] mt-1">
              {totalFixes} fixes generated • {applyableFixes} can be auto-applied
              {stack?.has_dbt && ' (dbt detected)'}
            </p>
          </div>
          {stack && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-[var(--muted)]">Your stack:</span>
              {stack.has_dbt && <span className="px-2 py-0.5 rounded bg-orange-500/20 text-orange-400">dbt</span>}
              {stack.primary_warehouse && (
                <span className="px-2 py-0.5 rounded bg-blue-500/20 text-blue-400">
                  {stack.primary_warehouse}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {results.length === 0 ? (
        <div className="dashboard-card p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-[var(--subtle-bg)] flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h4 className="font-medium mb-2">No Auto-Fixes Available</h4>
          <p className="text-sm text-[var(--muted)]">
            No findings in this report have available auto-fixes.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {results.map((result) => (
            <div key={result.finding_id} className="dashboard-card overflow-hidden">
              {/* Finding Context Header */}
              <div className="p-4 bg-gradient-to-r from-[var(--overlay-faint)] to-transparent border-b border-[var(--subtle-border)]">
                <div className="flex items-start gap-3">
                  {/* Severity indicator */}
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${
                    result.finding_severity === 'critical' ? 'bg-red-500/15' :
                    result.finding_severity === 'high' ? 'bg-amber-500/15' :
                    result.finding_severity === 'medium' ? 'bg-blue-500/15' : 'bg-emerald-500/15'
                  }`}>
                    {result.finding_severity === 'critical' ? (
                      <svg className="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                    ) : result.finding_severity === 'high' ? (
                      <svg className="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    ) : (
                      <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider">Finding</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                        result.finding_severity === 'critical' ? 'bg-red-500/15 text-red-400' :
                        result.finding_severity === 'high' ? 'bg-amber-500/15 text-amber-400' :
                        result.finding_severity === 'medium' ? 'bg-blue-500/15 text-blue-400' : 'bg-emerald-500/15 text-emerald-400'
                      }`}>
                        {result.finding_severity}
                      </span>
                    </div>
                    <h4 className="font-semibold text-[var(--text)]">{result.finding_title}</h4>
                    {result.finding_table && (
                      <div className="flex items-center gap-1.5 mt-1.5">
                        <svg className="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                        </svg>
                        <code className="text-xs text-purple-300 bg-purple-500/10 px-1.5 py-0.5 rounded">{result.finding_table}</code>
                      </div>
                    )}
                  </div>
                  
                  {/* Arrow indicator */}
                  <div className="flex items-center gap-2 text-emerald-400/60">
                    <span className="text-xs font-medium">Fix below</span>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                    </svg>
                  </div>
                </div>
              </div>
              
              {/* Fix Content */}
              <div className="p-4">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xs font-medium text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    Smart Fix
                  </span>
                  <div className="flex-1 h-px bg-emerald-500/20" />
                </div>
                <SmartFixes 
                  fixes={result.fixes} 
                  findingTitle={result.finding_title}
                  findingId={result.finding_id}
                  reportId={reportId}
                  table={result.finding_table}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
