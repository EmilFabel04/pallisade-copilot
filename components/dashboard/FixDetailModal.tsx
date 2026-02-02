'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { toast } from 'sonner';
import { useRouter } from 'next/navigation';
import { useFixTest } from './FixTestContext';

interface Fix {
  id: string;
  title: string;
  description: string;
  stack: string;
  language: string;
  confidence: 'high' | 'medium' | 'low';
  confidenceScore?: number;
  effort: 'instant' | 'minutes' | 'hours' | 'days';
  code: string;
  file_path?: string;
  why: string;
  priority: number;
  source?: 'template' | 'rag' | 'learned';
  similarFixesCount?: number;
  similarFixesSuccessRate?: number;
  reasoning?: string;
  type?: string;
  steps?: string[];
}

interface Finding {
  id: string;
  title: string;
  severity: string;
  table?: string;
  column?: string;
  scan_type?: string;
  category?: string;
}

interface FixDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  fix: Fix | null;
  finding?: Finding | null;
  reportId?: string;
  onApply?: () => void;
  onBackToFinding?: () => void;
}

const STACK_ICONS: Record<string, { icon: string; color: string }> = {
  dbt: { icon: '🔧', color: 'bg-orange-500/20 text-orange-400 border-orange-500/30' },
  snowflake: { icon: '❄️', color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' },
  bigquery: { icon: '🔷', color: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30' },
  redshift: { icon: '🔴', color: 'bg-red-500/20 text-red-400 border-red-500/30' },
  airflow: { icon: '🌀', color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
  python: { icon: '🐍', color: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' },
  sql: { icon: '📝', color: 'bg-purple-500/20 text-purple-400 border-purple-500/30' },
  yaml: { icon: '📄', color: 'bg-pink-500/20 text-pink-400 border-pink-500/30' },
};

const CONFIDENCE_CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  high: { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', label: 'High Confidence' },
  medium: { color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30', label: 'Medium Confidence' },
  low: { color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30', label: 'Needs Review' },
};

const EFFORT_CONFIG: Record<string, { icon: string; label: string; description: string }> = {
  instant: { icon: '⚡', label: 'Instant', description: 'Copy & paste' },
  minutes: { icon: '⏱️', label: 'Minutes', description: '5-15 min to apply' },
  hours: { icon: '🕐', label: 'Hours', description: '1-4 hours to apply' },
  days: { icon: '📅', label: 'Days', description: 'Multi-day effort' },
};

const SOURCE_CONFIG: Record<string, { icon: string; label: string; color: string }> = {
  template: { icon: '📋', label: 'Template Fix', color: 'text-blue-400' },
  rag: { icon: '🔍', label: 'Similar Fixes Found', color: 'text-purple-400' },
  learned: { icon: '🧠', label: 'ML Recommended', color: 'text-emerald-400' },
};

export function FixDetailModal({
  isOpen,
  onClose,
  fix,
  finding,
  reportId,
  onApply,
  onBackToFinding
}: FixDetailModalProps) {
  const router = useRouter();
  const { setFixToTest } = useFixTest();
  const [copied, setCopied] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [activeSection, setActiveSection] = useState<'code' | 'steps' | 'preview'>('code');
  
  useEffect(() => {
    setMounted(true);
  }, []);
  
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    
    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    }
    
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);
  
  const handleCopy = async () => {
    if (!fix?.code) return;
    try {
      await navigator.clipboard.writeText(fix.code);
      setCopied(true);
      toast.success('Code copied to clipboard!');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Failed to copy');
    }
  };
  
  const handleTestInSandbox = () => {
    if (!fix) return;
    
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
      findingId: finding?.id,
      findingTitle: finding?.title,
      findingSeverity: finding?.severity,
      reportId,
      table: finding?.table,
      column: finding?.column,
      issueType: finding?.scan_type,
      issueCategory: finding?.category,
      sourceDialect: fix.stack === 'snowflake' ? 'snowflake' : 
                     fix.stack === 'bigquery' ? 'bigquery' : 
                     fix.stack === 'redshift' ? 'redshift' : 'snowflake',
      generationMethod: fix.source || 'template',
    });
    
    router.push('/dashboard/sandbox');
    toast.info('Opening Sandbox Lab to test fix...');
    onClose();
  };
  
  if (!mounted || !isOpen || !fix) return null;
  
  const stackConfig = STACK_ICONS[fix.stack] || STACK_ICONS.sql;
  const confidenceConfig = CONFIDENCE_CONFIG[fix.confidence] || CONFIDENCE_CONFIG.medium;
  const effortConfig = EFFORT_CONFIG[fix.effort] || EFFORT_CONFIG.minutes;
  const sourceConfig = fix.source ? SOURCE_CONFIG[fix.source] : null;
  
  // Syntax highlighting helpers
  const formatCode = (code: string, language: string) => {
    // Simple syntax highlighting
    if (language === 'yaml' || language === 'yml') {
      return code
        .replace(/^(\s*-\s)/gm, '<span class="text-amber-400">$1</span>')
        .replace(/^(\s*\w+):/gm, '<span class="text-cyan-400">$1</span>:')
        .replace(/(#.*$)/gm, '<span class="text-gray-500">$1</span>');
    }
    if (language === 'sql') {
      return code
        .replace(/\b(SELECT|FROM|WHERE|AND|OR|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|CREATE|INSERT|UPDATE|DELETE|ALTER|DROP|TABLE|VIEW|INDEX|DISTINCT|ORDER BY|GROUP BY|HAVING|LIMIT|OFFSET|UNION|NULL|NOT|IS|IN|BETWEEN|LIKE|EXISTS|CASE|WHEN|THEN|ELSE|END)\b/gi, 
          '<span class="text-purple-400 font-medium">$1</span>')
        .replace(/'([^']*)'/g, '<span class="text-emerald-400">\'$1\'</span>')
        .replace(/(--.*$)/gm, '<span class="text-gray-500">$1</span>');
    }
    if (language === 'python') {
      return code
        .replace(/\b(def|class|import|from|return|if|else|elif|for|while|try|except|finally|with|as|pass|break|continue|lambda|yield|async|await|True|False|None)\b/g, 
          '<span class="text-purple-400 font-medium">$1</span>')
        .replace(/(#.*$)/gm, '<span class="text-gray-500">$1</span>')
        .replace(/'([^']*)'/g, '<span class="text-emerald-400">\'$1\'</span>')
        .replace(/"([^"]*)"/g, '<span class="text-emerald-400">"$1"</span>');
    }
    return code;
  };
  
  const content = (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/80 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative w-full max-w-3xl max-h-[90vh] bg-[#0c0c14] border border-[rgba(255,255,255,0.08)] rounded-2xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[rgba(255,255,255,0.06)] bg-gradient-to-r from-emerald-500/10 to-teal-500/10">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              {/* Stack icon */}
              <div className={`w-12 h-12 rounded-xl ${stackConfig.color} border flex items-center justify-center`}>
                <span className="text-2xl">{stackConfig.icon}</span>
              </div>
              
              <div>
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  {/* Confidence badge */}
                  <span className={`px-2 py-0.5 rounded text-xs font-medium border ${confidenceConfig.bg}`}>
                    {fix.confidenceScore ? `${Math.round(fix.confidenceScore * 100)}%` : confidenceConfig.label}
                  </span>
                  {/* Source badge */}
                  {sourceConfig && (
                    <span className={`px-2 py-0.5 rounded text-xs font-medium bg-[rgba(255,255,255,0.05)] ${sourceConfig.color} flex items-center gap-1`}>
                      <span>{sourceConfig.icon}</span>
                      {sourceConfig.label}
                    </span>
                  )}
                  {/* Effort badge */}
                  <span className="px-2 py-0.5 rounded text-xs bg-[rgba(255,255,255,0.05)] text-[var(--muted)]">
                    {effortConfig.icon} {effortConfig.label}
                  </span>
                </div>
                <h2 className="text-xl font-bold text-white">{fix.title}</h2>
                <p className="text-sm text-[var(--muted)] mt-1">{fix.description}</p>
              </div>
            </div>
            
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-[rgba(255,255,255,0.05)] transition-colors"
            >
              <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          
          {/* Finding reference */}
          {finding && (
            <div className="mt-3 pt-3 border-t border-[rgba(255,255,255,0.06)]">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-[var(--muted)]">Fixing:</span>
                <span className={`w-2 h-2 rounded-full ${
                  finding.severity === 'critical' ? 'bg-red-500' :
                  finding.severity === 'high' ? 'bg-amber-500' :
                  finding.severity === 'medium' ? 'bg-blue-500' : 'bg-emerald-500'
                }`} />
                <span className="font-medium">{finding.title}</span>
                {finding.table && (
                  <code className="text-xs text-[var(--muted)] ml-2">{finding.table}</code>
                )}
                {onBackToFinding && (
                  <button 
                    onClick={onBackToFinding}
                    className="ml-auto text-xs text-[var(--accent-2)] hover:underline"
                  >
                    ← Back to finding
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
        
        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {/* Why this fix */}
          <div className="px-6 py-4 bg-[rgba(255,255,255,0.02)] border-b border-[rgba(255,255,255,0.06)]">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <div className="text-sm font-medium text-blue-400 mb-1">Why This Fix?</div>
                <p className="text-sm text-[var(--muted)] leading-relaxed">{fix.why}</p>
              </div>
            </div>
            
            {/* Learning evidence */}
            {fix.similarFixesCount && fix.similarFixesCount > 0 && (
              <div className="mt-3 p-3 rounded-lg bg-[rgba(255,255,255,0.02)] border border-[var(--border-dim)]">
                <div className="flex items-center gap-4 text-sm">
                  <div className="flex items-center gap-1.5">
                    <span className="text-purple-400">📊</span>
                    <span className="text-[var(--muted)]">Similar fixes applied:</span>
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
          
          {/* Section tabs */}
          <div className="px-6 py-2 border-b border-[rgba(255,255,255,0.06)] flex gap-1">
            <button
              onClick={() => setActiveSection('code')}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2 ${
                activeSection === 'code'
                  ? 'bg-emerald-500/10 text-emerald-400'
                  : 'text-[var(--muted)] hover:text-white hover:bg-[rgba(255,255,255,0.04)]'
              }`}
            >
              <span>💻</span>
              Code
            </button>
            {fix.steps && fix.steps.length > 0 && (
              <button
                onClick={() => setActiveSection('steps')}
                className={`px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2 ${
                  activeSection === 'steps'
                    ? 'bg-blue-500/10 text-blue-400'
                    : 'text-[var(--muted)] hover:text-white hover:bg-[rgba(255,255,255,0.04)]'
                }`}
              >
                <span>📝</span>
                Steps
              </button>
            )}
            <button
              onClick={() => setActiveSection('preview')}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2 ${
                activeSection === 'preview'
                  ? 'bg-purple-500/10 text-purple-400'
                  : 'text-[var(--muted)] hover:text-white hover:bg-[rgba(255,255,255,0.04)]'
              }`}
            >
              <span>👁️</span>
              Preview
            </button>
          </div>
          
          {/* Code section */}
          {activeSection === 'code' && (
            <div className="p-6">
              {/* File path */}
              {fix.file_path && (
                <div className="mb-4 flex items-center gap-2">
                  <span className="text-xs text-[var(--muted)]">Add to file:</span>
                  <code className="text-sm text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded">{fix.file_path}</code>
                </div>
              )}
              
              {/* Code block */}
              <div className="rounded-xl overflow-hidden border border-emerald-500/20 bg-[rgba(0,0,0,0.4)]">
                {/* Code header */}
                <div className="px-4 py-2 bg-emerald-500/10 border-b border-emerald-500/20 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-emerald-400">{stackConfig.icon}</span>
                    <span className="text-xs font-medium text-emerald-400 uppercase">{fix.language}</span>
                  </div>
                  <button
                    onClick={handleCopy}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 ${
                      copied
                        ? 'bg-emerald-500/30 text-emerald-400'
                        : 'bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30'
                    }`}
                  >
                    {copied ? (
                      <>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                        Copied!
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                        Copy Code
                      </>
                    )}
                  </button>
                </div>
                
                {/* Code content */}
                <pre className="p-4 text-sm font-mono overflow-x-auto leading-relaxed max-h-80">
                  <code 
                    className="text-emerald-300/90"
                    dangerouslySetInnerHTML={{ __html: formatCode(fix.code, fix.language) }}
                  />
                </pre>
                
                {/* Code footer hint */}
                <div className="px-4 py-2 bg-emerald-500/5 border-t border-emerald-500/10 flex items-center gap-2 text-xs text-emerald-400/70">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {fix.type === 'dbt_test' && 'Add this to your dbt schema.yml file'}
                  {fix.type === 'dbt_source' && 'Add this to your dbt _sources.yml file'}
                  {fix.type === 'dbt_docs' && 'Add this documentation to your schema.yml'}
                  {fix.type === 'sql' && 'Run this SQL in your data warehouse'}
                  {!['dbt_test', 'dbt_source', 'dbt_docs', 'sql'].includes(fix.type || '') && 'Apply this fix to resolve the issue'}
                </div>
              </div>
            </div>
          )}
          
          {/* Steps section */}
          {activeSection === 'steps' && fix.steps && (
            <div className="p-6">
              <div className="space-y-3">
                {fix.steps.map((step, i) => (
                  <div key={i} className="flex gap-4 p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)]">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold">
                      {i + 1}
                    </div>
                    <div className="flex-1 pt-1">
                      <p className="text-sm text-[var(--text)]">{step.replace(/^\d+\.\s*/, '')}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Preview section */}
          {activeSection === 'preview' && (
            <div className="p-6">
              <div className="space-y-4">
                <div className="p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)]">
                  <h3 className="text-sm font-medium mb-3">Before vs After</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-xs text-red-400 mb-2 flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-red-400" />
                        Before
                      </div>
                      <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/20 text-sm text-[var(--muted)]">
                        Issue detected: {finding?.title || 'Data quality issue'}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-emerald-400 mb-2 flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-emerald-400" />
                        After
                      </div>
                      <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20 text-sm text-[var(--muted)]">
                        {fix.description || 'Issue resolved with applied fix'}
                      </div>
                    </div>
                  </div>
                </div>
                
                {/* Expected impact */}
                <div className="p-4 rounded-xl bg-blue-500/5 border border-blue-500/20">
                  <h3 className="text-sm font-medium text-blue-400 mb-3">Expected Impact</h3>
                  <ul className="space-y-2 text-sm">
                    <li className="flex items-start gap-2">
                      <span className="text-blue-400 mt-0.5">✓</span>
                      <span className="text-[var(--muted)]">Issue will be prevented in future runs</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <span className="text-blue-400 mt-0.5">✓</span>
                      <span className="text-[var(--muted)]">Data quality score will improve</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <span className="text-blue-400 mt-0.5">✓</span>
                      <span className="text-[var(--muted)]">Downstream tables will receive cleaner data</span>
                    </li>
                  </ul>
                </div>
                
                {/* Risk assessment */}
                <div className="p-4 rounded-xl bg-amber-500/5 border border-amber-500/20">
                  <h3 className="text-sm font-medium text-amber-400 mb-3">Risk Assessment</h3>
                  <div className="flex items-center gap-4">
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-[var(--muted)]">Risk Level</span>
                        <span className={`text-xs font-medium ${
                          fix.confidence === 'high' ? 'text-emerald-400' : 
                          fix.confidence === 'medium' ? 'text-amber-400' : 'text-red-400'
                        }`}>
                          {fix.confidence === 'high' ? 'Low Risk' : 
                           fix.confidence === 'medium' ? 'Medium Risk' : 'High Risk'}
                        </span>
                      </div>
                      <div className="h-2 bg-[rgba(255,255,255,0.05)] rounded-full overflow-hidden">
                        <div 
                          className={`h-full rounded-full ${
                            fix.confidence === 'high' ? 'bg-emerald-500' : 
                            fix.confidence === 'medium' ? 'bg-amber-500' : 'bg-red-500'
                          }`}
                          style={{ width: fix.confidence === 'high' ? '25%' : fix.confidence === 'medium' ? '50%' : '75%' }}
                        />
                      </div>
                    </div>
                  </div>
                  <p className="text-xs text-[var(--muted)] mt-2">
                    {fix.confidence === 'high' 
                      ? 'This fix has been validated and has a high success rate.'
                      : fix.confidence === 'medium'
                      ? 'This fix should work but recommend testing in sandbox first.'
                      : 'Review this fix carefully before applying. Consider testing in sandbox.'}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
        
        {/* Footer */}
        <div className="px-6 py-4 border-t border-[rgba(255,255,255,0.06)] bg-[rgba(0,0,0,0.3)] flex items-center justify-between">
          <div className="text-xs text-[var(--muted)]">
            {effortConfig.icon} {effortConfig.description}
          </div>
          <div className="flex items-center gap-2">
            {/* Test in Sandbox */}
            <button
              onClick={handleTestInSandbox}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-blue-500/20 to-cyan-500/20 text-cyan-400 border border-cyan-500/30 hover:from-blue-500/30 hover:to-cyan-500/30 transition-all flex items-center gap-2"
            >
              <span>🧪</span>
              Test in Sandbox
            </button>
            
            {/* Apply button */}
            {onApply && (
              <button
                onClick={onApply}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-emerald-600 to-teal-600 text-white hover:from-emerald-500 hover:to-teal-500 transition-all flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                </svg>
                Apply to GitHub
              </button>
            )}
            
            {/* Copy button */}
            <button
              onClick={handleCopy}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${
                copied
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)]'
              }`}
            >
              {copied ? '✓ Copied!' : '📋 Copy Code'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
  
  return createPortal(content, document.body);
}
