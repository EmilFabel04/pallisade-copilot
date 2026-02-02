"use client";

/**
 * Test Fix Modal
 * 
 * Tests fixes in an isolated DuckDB sandbox before applying to production.
 * Shows before/after comparison and confidence scoring.
 */

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";

interface Fix {
  id: string;
  title: string;
  code: string;
  language: string;
  stack: string;
  confidence: string;
}

interface ValidationResult {
  name: string;
  passed: boolean;
  message: string;
  beforeValue?: unknown;
  afterValue?: unknown;
  importance: string;
}

interface TestResult {
  status: "passed" | "failed" | "error" | "warning" | "skipped";
  confidenceScore: number;
  confidenceReasons: string[];
  durationMs: number;
  originalSql: string;
  translatedSql: string;
  tableName: string;
  rowCount: number;
  validations: ValidationResult[];
  beforeSnapshot: Record<string, unknown>;
  afterSnapshot: Record<string, unknown>;
  changes: Record<string, unknown>;
  warnings: string[];
  errors: string[];
}

interface TestFixModalProps {
  isOpen: boolean;
  onClose: () => void;
  fix: Fix;
  table?: string;
  columns?: Array<{
    name: string;
    dataType: string;
    nullRate?: number;
  }>;
  sourceDialect?: string;
  targetColumn?: string;
}

const STATUS_STYLES: Record<string, { bg: string; text: string; icon: string }> = {
  passed: { 
    bg: "bg-emerald-500/20", 
    text: "text-emerald-400",
    icon: "✓"
  },
  warning: { 
    bg: "bg-amber-500/20", 
    text: "text-amber-400",
    icon: "⚠"
  },
  failed: { 
    bg: "bg-red-500/20", 
    text: "text-red-400",
    icon: "✕"
  },
  error: { 
    bg: "bg-red-500/20", 
    text: "text-red-400",
    icon: "!"
  },
  skipped: { 
    bg: "bg-gray-500/20", 
    text: "text-gray-400",
    icon: "○"
  },
};

export function TestFixModal({
  isOpen,
  onClose,
  fix,
  table = "unknown_table",
  columns = [],
  sourceDialect = "snowflake",
  targetColumn,
}: TestFixModalProps) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  
  // Default columns if none provided
  const defaultColumns = columns.length > 0 ? columns : [
    { name: "id", dataType: "INTEGER", nullRate: 0 },
    { name: "amount", dataType: "FLOAT", nullRate: 0.05 },
    { name: "status", dataType: "VARCHAR", nullRate: 0.02 },
    { name: "created_at", dataType: "TIMESTAMP", nullRate: 0 },
  ];

  const runTest = async () => {
    setTesting(true);
    setResult(null);
    
    try {
      const response = await fetch("/api/sandbox/test-fix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fixSql: fix.code,
          tableName: table,
          columns: defaultColumns.map(col => ({
            name: col.name,
            dataType: col.dataType,
            nullRate: col.nullRate ?? 0.05,
            // Add some default stats for numeric columns
            minValue: (col.dataType || '').toLowerCase().includes('int') || (col.dataType || '').toLowerCase().includes('float') ? 0 : undefined,
            maxValue: (col.dataType || '').toLowerCase().includes('int') || (col.dataType || '').toLowerCase().includes('float') ? 10000 : undefined,
            mean: (col.dataType || '').toLowerCase().includes('float') ? 500 : undefined,
            stdDev: (col.dataType || '').toLowerCase().includes('float') ? 250 : undefined,
          })),
          sourceDialect,
          targetColumn: targetColumn || undefined,
          rowCount: 1000,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.details || error.error || "Test failed");
      }

      const rawResult = await response.json();
      
      // Normalize snake_case to camelCase (API returns snake_case)
      const testResult: TestResult = {
        status: rawResult.status,
        confidenceScore: rawResult.confidence_score ?? rawResult.confidenceScore ?? 0,
        confidenceReasons: rawResult.confidence_reasons ?? rawResult.confidenceReasons ?? [],
        durationMs: rawResult.duration_ms ?? rawResult.durationMs ?? 0,
        originalSql: rawResult.original_sql ?? rawResult.originalSql ?? "",
        translatedSql: rawResult.translated_sql ?? rawResult.translatedSql ?? "",
        tableName: rawResult.table_name ?? rawResult.tableName ?? "",
        rowCount: rawResult.row_count ?? rawResult.rowCount ?? 0,
        validations: (rawResult.validations ?? []).map((v: Record<string, unknown>) => ({
          name: v.name,
          passed: v.passed,
          message: v.message,
          beforeValue: v.before_value ?? v.beforeValue,
          afterValue: v.after_value ?? v.afterValue,
          importance: v.importance ?? "medium",
        })),
        beforeSnapshot: rawResult.before_snapshot ?? rawResult.beforeSnapshot ?? {},
        afterSnapshot: rawResult.after_snapshot ?? rawResult.afterSnapshot ?? {},
        changes: rawResult.changes ?? {},
        warnings: rawResult.warnings ?? [],
        errors: rawResult.errors ?? [],
      };
      
      setResult(testResult);
      
      if (testResult.status === "passed") {
        toast.success(`Fix tested successfully! Confidence: ${Math.round(testResult.confidenceScore * 100)}%`);
      } else if (testResult.status === "warning") {
        toast.warning("Fix works with warnings. Review the results.");
      } else {
        toast.error("Fix failed validation. Review the errors.");
      }
      
    } catch (error) {
      console.error("Test error:", error);
      toast.error(error instanceof Error ? error.message : "Failed to test fix");
      setResult({
        status: "error",
        confidenceScore: 0,
        confidenceReasons: [],
        durationMs: 0,
        originalSql: fix.code,
        translatedSql: fix.code,
        tableName: table,
        rowCount: 0,
        validations: [],
        beforeSnapshot: {},
        afterSnapshot: {},
        changes: {},
        warnings: [],
        errors: [error instanceof Error ? error.message : "Unknown error"],
      });
    } finally {
      setTesting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
      >
        {/* Backdrop */}
        <div 
          className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          onClick={onClose}
        />
        
        {/* Modal */}
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }}
          className="relative w-full max-w-3xl max-h-[85vh] overflow-y-auto bg-[var(--card)] rounded-2xl border border-[var(--border-dim)] shadow-2xl"
        >
          {/* Header */}
          <div className="sticky top-0 z-10 bg-[var(--card)] border-b border-[var(--border-dim)] p-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  🧪 Test Fix in Sandbox
                </h2>
                <p className="text-sm text-[var(--muted)] mt-1">
                  Test safely in an isolated DuckDB environment
                </p>
              </div>
              <button
                onClick={onClose}
                className="p-2 rounded-lg hover:bg-[rgba(255,255,255,0.05)] transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="p-6 space-y-6">
            {/* Fix Info */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{fix.title}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  fix.confidence === 'high' ? 'bg-emerald-500/20 text-emerald-400' :
                  fix.confidence === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                  'bg-gray-500/20 text-gray-400'
                }`}>
                  {fix.confidence} confidence
                </span>
              </div>
              
              <pre className="text-xs bg-[rgba(0,0,0,0.3)] p-4 rounded-xl overflow-x-auto max-h-40">
                <code className="text-green-400">{fix.code}</code>
              </pre>
            </div>

            {/* Test Context */}
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div className="p-3 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[var(--border-dim)]">
                <span className="text-[var(--muted)]">Table:</span>
                <span className="ml-2 font-mono">{table}</span>
              </div>
              <div className="p-3 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[var(--border-dim)]">
                <span className="text-[var(--muted)]">Dialect:</span>
                <span className="ml-2 capitalize">{sourceDialect}</span>
              </div>
            </div>

            {/* Run Test Button */}
            {!result && (
              <button
                onClick={runTest}
                disabled={testing}
                className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all font-medium flex items-center justify-center gap-2"
              >
                {testing ? (
                  <>
                    <svg className="animate-spin w-5 h-5" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    Testing fix in sandbox...
                  </>
                ) : (
                  <>
                    🚀 Run Sandbox Test
                  </>
                )}
              </button>
            )}

            {/* Test Results */}
            {result && (
              <div className="space-y-4">
                {/* Status Banner */}
                <div className={`p-4 rounded-xl ${STATUS_STYLES[result.status].bg} border border-${STATUS_STYLES[result.status].text.replace('text-', '')}/30`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className={`text-2xl`}>
                        {STATUS_STYLES[result.status].icon}
                      </span>
                      <div>
                        <div className={`font-semibold capitalize ${STATUS_STYLES[result.status].text}`}>
                          Test {result.status}
                        </div>
                        <div className="text-sm text-[var(--muted)]">
                          Completed in {result.durationMs}ms
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-2xl font-bold">
                        {Math.round(result.confidenceScore * 100)}%
                      </div>
                      <div className="text-xs text-[var(--muted)]">Confidence</div>
                    </div>
                  </div>
                </div>

                {/* Confidence Breakdown */}
                {result.confidenceReasons.length > 0 && (
                  <div className="p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[var(--border-dim)]">
                    <h4 className="text-sm font-medium mb-2">Confidence Breakdown</h4>
                    <ul className="space-y-1">
                      {result.confidenceReasons.map((reason, i) => (
                        <li key={i} className="text-xs text-[var(--muted)] flex items-start gap-2">
                          <span>•</span>
                          <span>{reason}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Validations */}
                {result.validations.length > 0 && (
                  <div className="p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[var(--border-dim)]">
                    <h4 className="text-sm font-medium mb-3">Validation Results</h4>
                    <div className="space-y-2">
                      {result.validations.map((v, i) => (
                        <div key={i} className={`p-3 rounded-lg flex items-center justify-between ${
                          v.passed ? 'bg-emerald-500/10' : 'bg-red-500/10'
                        }`}>
                          <div className="flex items-center gap-2">
                            <span className={v.passed ? 'text-emerald-400' : 'text-red-400'}>
                              {v.passed ? '✓' : '✕'}
                            </span>
                            <span className="text-sm">{v.message}</span>
                          </div>
                          {(v.beforeValue !== undefined || v.afterValue !== undefined) && (
                            <div className="text-xs text-[var(--muted)]">
                              {v.beforeValue !== undefined && <span>{String(v.beforeValue)}</span>}
                              {v.beforeValue !== undefined && v.afterValue !== undefined && <span> → </span>}
                              {v.afterValue !== undefined && <span className={v.passed ? 'text-emerald-400' : ''}>{String(v.afterValue)}</span>}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Changes */}
                {Object.keys(result.changes).length > 0 && (
                  <div className="p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[var(--border-dim)]">
                    <h4 className="text-sm font-medium mb-3">Changes Applied</h4>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      {Object.entries(result.changes).map(([key, value]) => (
                        <div key={key} className="p-2 rounded bg-[rgba(0,0,0,0.2)]">
                          <span className="text-[var(--muted)]">{key.replace(/_/g, ' ')}:</span>
                          <span className="ml-2 font-mono">{String(value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Warnings */}
                {result.warnings.length > 0 && (
                  <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30">
                    <h4 className="text-sm font-medium text-amber-400 mb-2">⚠ Warnings</h4>
                    <ul className="space-y-1">
                      {result.warnings.map((w, i) => (
                        <li key={i} className="text-xs text-amber-300">{w}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Errors */}
                {result.errors.length > 0 && (
                  <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30">
                    <h4 className="text-sm font-medium text-red-400 mb-2">✕ Errors</h4>
                    <ul className="space-y-1">
                      {result.errors.map((e, i) => (
                        <li key={i} className="text-xs text-red-300">{e}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Actions */}
                <div className="flex gap-3">
                  <button
                    onClick={() => setResult(null)}
                    className="flex-1 py-2.5 px-4 rounded-xl bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] transition-colors"
                  >
                    Test Again
                  </button>
                  <button
                    onClick={onClose}
                    className="flex-1 py-2.5 px-4 rounded-xl bg-[var(--accent)] hover:bg-[var(--accent-2)] transition-colors"
                  >
                    {result.status === 'passed' ? 'Continue to Apply' : 'Close'}
                  </button>
                </div>
              </div>
            )}

            {/* Info Footer */}
            <div className="text-xs text-[var(--muted)] text-center pt-2 border-t border-[var(--border-dim)]">
              🔒 Tests run in an isolated DuckDB environment with synthetic data.
              No production data is accessed.
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

