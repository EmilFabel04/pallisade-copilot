// ============================================
// FINDING DEDUPLICATION UTILITIES
// ============================================

import crypto from 'crypto';

export interface Finding {
  id?: string;
  table?: string;
  column?: string;
  title?: string;
  description?: string;
  severity?: string;
  scan_type?: string;
  finding_type?: string;
  category?: string;
  fingerprint?: string;
  [key: string]: any;
}

/**
 * Generate a unique fingerprint for a finding.
 * Findings with the same fingerprint are considered duplicates.
 * 
 * Fingerprint is based on:
 * - Table name
 * - Column name (if applicable)
 * - Finding type (null_rate, negative_value, stale, etc.)
 * - Severity
 */
export function generateFindingFingerprint(finding: Finding): string {
  const components = [
    (finding.table || '').toLowerCase().trim(),
    (finding.column || '').toLowerCase().trim(),
    (finding.finding_type || finding.scan_type || '').toLowerCase().trim(),
    (finding.severity || '').toLowerCase().trim(),
  ].filter(Boolean);
  
  // Create a hash of the components
  const hash = crypto.createHash('sha256')
    .update(components.join('::'))
    .digest('hex')
    .substring(0, 16);
  
  return hash;
}

/**
 * Add fingerprints to all findings in an array
 */
export function addFingerprints(findings: Finding[]): Finding[] {
  return findings.map(f => ({
    ...f,
    fingerprint: f.fingerprint || generateFindingFingerprint(f),
  }));
}

/**
 * Deduplicate findings by fingerprint.
 * Returns unique findings, keeping the most recent one if duplicates exist.
 */
export function deduplicateFindings(findings: Finding[]): Finding[] {
  const fingerprintMap = new Map<string, Finding>();
  
  for (const finding of findings) {
    const fingerprint = finding.fingerprint || generateFindingFingerprint(finding);
    
    // If we haven't seen this fingerprint, or this finding is more recent, keep it
    if (!fingerprintMap.has(fingerprint)) {
      fingerprintMap.set(fingerprint, { ...finding, fingerprint });
    }
  }
  
  return Array.from(fingerprintMap.values());
}

/**
 * Count unique findings by severity across multiple reports.
 * Returns both total counts and unique counts.
 */
export function countUniqueFindings(allFindings: Finding[]): {
  total: number;
  unique: number;
  duplicates: number;
  bySeverity: {
    critical: { total: number; unique: number };
    high: { total: number; unique: number };
    medium: { total: number; unique: number };
    low: { total: number; unique: number };
  };
} {
  const fingerprintsWithFindings = addFingerprints(allFindings);
  const uniqueFindings = deduplicateFindings(fingerprintsWithFindings);
  
  const countBySeverity = (findings: Finding[], severity: string) =>
    findings.filter(f => (f.severity || '').toLowerCase() === severity.toLowerCase()).length;
  
  return {
    total: allFindings.length,
    unique: uniqueFindings.length,
    duplicates: allFindings.length - uniqueFindings.length,
    bySeverity: {
      critical: {
        total: countBySeverity(allFindings, 'critical'),
        unique: countBySeverity(uniqueFindings, 'critical'),
      },
      high: {
        total: countBySeverity(allFindings, 'high'),
        unique: countBySeverity(uniqueFindings, 'high'),
      },
      medium: {
        total: countBySeverity(allFindings, 'medium'),
        unique: countBySeverity(uniqueFindings, 'medium'),
      },
      low: {
        total: countBySeverity(allFindings, 'low'),
        unique: countBySeverity(uniqueFindings, 'low'),
      },
    },
  };
}

/**
 * Get unique findings across multiple reports.
 * Each report's findings are preserved, but duplicates across reports
 * are marked and only counted once in totals.
 */
export function getUniqueFindingsAcrossReports(
  reports: Array<{ id: string; findings: Finding[] }>
): {
  uniqueFindings: Finding[];
  totalUnique: number;
  reportStats: Array<{
    reportId: string;
    total: number;
    unique: number;
    duplicatesFromPreviousScans: number;
  }>;
} {
  const seenFingerprints = new Set<string>();
  const uniqueFindings: Finding[] = [];
  const reportStats: Array<{
    reportId: string;
    total: number;
    unique: number;
    duplicatesFromPreviousScans: number;
  }> = [];

  // Process reports in reverse chronological order (newest first)
  for (const report of reports) {
    const findings = report.findings || [];
    let uniqueInReport = 0;
    let duplicatesInReport = 0;

    for (const finding of findings) {
      const fingerprint = finding.fingerprint || generateFindingFingerprint(finding);
      
      if (!seenFingerprints.has(fingerprint)) {
        seenFingerprints.add(fingerprint);
        uniqueFindings.push({ ...finding, fingerprint });
        uniqueInReport++;
      } else {
        duplicatesInReport++;
      }
    }

    reportStats.push({
      reportId: report.id,
      total: findings.length,
      unique: uniqueInReport,
      duplicatesFromPreviousScans: duplicatesInReport,
    });
  }

  return {
    uniqueFindings,
    totalUnique: uniqueFindings.length,
    reportStats,
  };
}

/**
 * Calculate severity counts from unique findings
 */
export function calculateSeverityCounts(findings: Finding[]): {
  critical: number;
  high: number;
  medium: number;
  low: number;
  total: number;
} {
  const counts = {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    total: findings.length,
  };

  for (const finding of findings) {
    const severity = (finding.severity || '').toLowerCase();
    if (severity === 'critical') counts.critical++;
    else if (severity === 'high') counts.high++;
    else if (severity === 'medium') counts.medium++;
    else if (severity === 'low') counts.low++;
  }

  return counts;
}
