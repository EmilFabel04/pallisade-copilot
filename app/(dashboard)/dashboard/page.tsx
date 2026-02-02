import { getServerSession } from 'next-auth';
import { authOptions } from '../../../lib/auth';
import Link from 'next/link';
import prisma from '@/lib/db';
import { PipelineHealthClient } from '@/components/dashboard/PipelineHealthClient';
import { getUniqueFindingsAcrossReports, calculateSeverityCounts, Finding } from '@/lib/findings';

export const metadata = {
  title: 'Dashboard — Pallisade',
  description: 'Your data reliability command center',
};

const getScoreColor = (score: number) => {
  if (score >= 80) return 'text-emerald-400';
  if (score >= 60) return 'text-amber-400';
  return 'text-red-400';
};

const getScoreRingColor = (score: number) => {
  if (score >= 80) return 'stroke-emerald-500';
  if (score >= 60) return 'stroke-amber-500';
  return 'stroke-red-500';
};

export default async function DashboardPage() {
  const session = await getServerSession(authOptions);
  
  // Fetch real data
  let pipelineNodes: any[] = [];
  let pipelineStacks: any[] = [];
  let recentReports: any[] = [];
  let user = null;
  
  if (session?.user?.email) {
    user = await prisma.user.findUnique({
      where: { email: session.user.email },
      select: { id: true, organizationId: true },
    });
    
    if (user?.organizationId) {
      // Fetch from Pipeline system (primary)
      pipelineStacks = await prisma.pipelineStack.findMany({
        where: { organizationId: user.organizationId },
        include: {
          nodes: {
            select: { 
              id: true, 
              name: true, 
              layer: true, 
              toolType: true, 
              status: true,
              healthScore: true,
              findingsCount: true,
              criticalCount: true,
              highCount: true,
            },
          },
        },
      });
      
      // Flatten all nodes from all stacks
      pipelineNodes = pipelineStacks.flatMap(s => s.nodes);
      
      recentReports = await prisma.report.findMany({
        where: {
          OR: [
            { userId: user.id },
            { organizationId: user.organizationId },
          ],
        },
        orderBy: { createdAt: 'desc' },
        take: 5,
      });
    }
  }

  // Fetch scheduled scans
  let scheduledScans: any[] = [];
  if (user?.organizationId) {
    try {
      scheduledScans = await prisma.scanSchedule.findMany({
        where: { organizationId: user.organizationId, enabled: true },
        orderBy: { nextRunAt: 'asc' },
        take: 3,
      });
    } catch (e) {
      scheduledScans = [];
    }
  }

  // Calculate stats from real data with deduplication
  const completedReports = recentReports.filter(r => r.status === 'COMPLETED');
  
  // Collect all findings from all completed reports
  const allFindings: Finding[] = completedReports.flatMap(r => 
    ((r.findings as Finding[]) || [])
  );
  
  // Deduplicate findings across all reports
  const { uniqueFindings, totalUnique } = getUniqueFindingsAcrossReports(
    completedReports.map(r => ({ id: r.id, findings: (r.findings as Finding[]) || [] }))
  );
  
  // Calculate severity counts from unique findings only
  const uniqueCounts = calculateSeverityCounts(uniqueFindings);
  const totalFindings = uniqueCounts.total;
  const criticalCount = uniqueCounts.critical;
  
  // Map scan keys to report enum
  const reportTypeMap: Record<string, string> = {
    freshness: 'DATA_FRESHNESS',
    quality: 'DATA_QUALITY',
    schema: 'SCHEMA_DRIFT',
    secrets: 'PERIMETER_SECURITY',
  };

  // Get score per scan type, falling back to embedded multi-scan results
  const getScoreByType = (scanKey: keyof typeof reportTypeMap) => {
    const reportType = reportTypeMap[scanKey];
    // Prefer a dedicated report of this type
    const direct = completedReports.find(r => r.type === reportType && r.overallScore !== null);
    if (direct?.overallScore !== null && direct?.overallScore !== undefined) return direct.overallScore;

    // Fallback: look inside rawData.results_by_type from multi-scan reports
    const fallback = completedReports.find((r: any) => r.rawData?.results_by_type?.[scanKey]?.score !== undefined);
    if (fallback) {
      const score = (fallback as any).rawData?.results_by_type?.[scanKey]?.score;
      if (score !== undefined && score !== null) return score;
    }
    return null;
  };

  // Only show scores for scans that were actually run
  const scannerScores = {
    freshness: getScoreByType('freshness'),
    quality: getScoreByType('quality'),
    schema: getScoreByType('schema'),
    secrets: getScoreByType('secrets'),
  };

  // DRR = average of available scan scores (freshness/quality/schema/security)
  const contributingScores = Object.entries(scannerScores).filter(([, score]) => score !== null) as [string, number][];
  const latestScore = contributingScores.length
    ? Math.round(contributingScores.reduce((sum, [, score]) => sum + (score || 0), 0) / contributingScores.length)
    : 0;
  const contributingLabels = contributingScores.map(([key]) => key.charAt(0).toUpperCase() + key.slice(1)).join(', ');

  // Calculate MTTR (Mean Time to Resolve) - demo value for now
  // TODO: Calculate from actual finding resolution times
  const avgMttr = 127; // Demo value in minutes

  const formatDuration = (minutes: number) => {
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  };

  return (
    <div className="space-y-6">
      {/* Welcome */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">
            Welcome{session?.user?.name ? `, ${session.user.name.split(' ')[0]}` : ''}
          </h1>
          <p className="text-[var(--muted)] mt-1">Your data reliability command center</p>
        </div>
        <Link href="/dashboard/reports/new" className="btn btn-elevated">
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
          </svg>
          Run Scan
        </Link>
      </div>

      {/* Score & Key Metrics */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* DRR Score Card */}
        <div className="dashboard-card p-5 flex items-center gap-5">
          <div className="relative flex-shrink-0">
            <svg className="w-20 h-20 -rotate-90">
              <circle cx="40" cy="40" r="34" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="6" />
              <circle cx="40" cy="40" r="34" fill="none" className={getScoreRingColor(latestScore)} strokeWidth="6" strokeLinecap="round" strokeDasharray={`${(latestScore / 100) * 214} 214`} />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className={`text-xl font-black ${getScoreColor(latestScore)}`}>{latestScore}</span>
            </div>
          </div>
          <div>
            <div className="text-sm text-[var(--muted)]">DRR Score</div>
            <div className="text-2xl font-bold">
              {latestScore >= 80 ? 'Healthy' : latestScore >= 60 ? 'At Risk' : 'Critical'}
            </div>
            <div className="text-xs text-[var(--muted)] mt-1">
              Data Reliability Rating{contributingLabels ? ` · Based on ${contributingLabels}` : ''}
            </div>
          </div>
        </div>

        {/* MTTR */}
        <div className="dashboard-card p-5">
          <div className="text-xs text-[var(--muted)] uppercase tracking-wide mb-2">Avg MTTR</div>
          <div className="text-3xl font-bold">{formatDuration(avgMttr)}</div>
          <div className="text-xs text-[var(--muted)] mt-1">Mean Time to Resolve</div>
          <div className="mt-3 h-1.5 bg-[rgba(255,255,255,0.05)] rounded-full overflow-hidden">
            <div 
              className={`h-full rounded-full transition-all ${avgMttr <= 120 ? 'bg-emerald-500' : avgMttr <= 240 ? 'bg-amber-500' : 'bg-red-500'}`}
              style={{ width: `${Math.min(100, (120 / avgMttr) * 100)}%` }}
            />
          </div>
        </div>

        {/* High Priority Findings */}
        <div className="dashboard-card p-5">
          <div className="text-xs text-[var(--muted)] uppercase tracking-wide mb-2">High Priority</div>
          <div className="text-3xl font-bold text-orange-400">{uniqueCounts.high || 0}</div>
          <div className="text-xs text-[var(--muted)] mt-1">Requiring attention</div>
          <Link href="/dashboard/findings" className="text-xs text-[var(--accent-2)] hover:underline mt-3 block">
            View all →
          </Link>
        </div>

        {/* Critical Findings */}
        <div className="dashboard-card p-5">
          <div className="text-xs text-[var(--muted)] uppercase tracking-wide mb-2">Critical Issues</div>
          <div className={`text-3xl font-bold ${criticalCount > 0 ? 'text-red-400' : 'text-emerald-400'}`}>{criticalCount}</div>
          <div className="text-xs text-[var(--muted)] mt-1">From {completedReports.length} scans</div>
          <div className="text-xs text-[var(--muted)] mt-3">{totalFindings} total findings</div>
        </div>
      </div>

      {/* Scanner Health */}
      <div className="dashboard-card p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold">Scanner Health</h3>
          <Link href="/dashboard/reports" className="text-sm text-[var(--accent-2)] hover:underline">
            View all scans →
          </Link>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Object.entries(scannerScores).map(([key, score]) => (
            <div key={key} className="flex items-center gap-3 p-3 rounded-lg bg-[rgba(255,255,255,0.02)]">
              <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${
                score === null ? 'bg-[rgba(255,255,255,0.03)]' :
                score >= 80 ? 'bg-emerald-500/10' : score >= 60 ? 'bg-amber-500/10' : 'bg-red-500/10'
              }`}>
                <span className={`text-lg font-bold ${
                  score === null ? 'text-[var(--muted)]' :
                  score >= 80 ? 'text-emerald-400' : score >= 60 ? 'text-amber-400' : 'text-red-400'
                }`}>{score ?? '—'}</span>
              </div>
              <div>
                <div className="text-sm font-medium capitalize">{key}</div>
                <div className="text-xs text-[var(--muted)]">
                  {score === null ? 'Not scanned' : score >= 80 ? 'Healthy' : score >= 60 ? 'Warning' : 'Critical'}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Pipeline Health (Client Component) */}
      <PipelineHealthClient />

      {/* Connected Sources Bar */}
      <div className="dashboard-card p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <span className="text-sm text-[var(--muted)]">Pipeline:</span>
            {pipelineNodes.length === 0 ? (
              <span className="text-sm text-amber-400">No pipeline configured</span>
            ) : (
              <div className="flex items-center gap-4">
                {pipelineNodes.slice(0, 5).map((node, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${
                      node.status === 'HEALTHY' || node.status === 'CONNECTED' 
                        ? 'bg-emerald-500' 
                        : node.status === 'WARNING' 
                          ? 'bg-yellow-500' 
                          : 'bg-gray-500'
                    }`} />
                    <span className="text-sm font-medium">{node.name}</span>
                    <span className="text-xs text-[var(--muted)]">({node.layer.toLowerCase()})</span>
                  </div>
                ))}
                {pipelineNodes.length > 5 && (
                  <span className="text-xs text-[var(--muted)]">+{pipelineNodes.length - 5} more</span>
                )}
              </div>
            )}
          </div>
          <Link href="/dashboard/pipeline" className="text-sm text-[var(--accent-2)] hover:underline">
            {pipelineNodes.length === 0 ? 'Build Pipeline' : 'Manage'} →
          </Link>
        </div>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Activity */}
        <div className="lg:col-span-2 dashboard-card">
          <div className="p-5 border-b border-[rgba(255,255,255,0.06)]">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Recent Scans</h2>
              <Link href="/dashboard/reports" className="text-sm text-[var(--accent-2)] hover:underline">
                View all →
              </Link>
            </div>
          </div>
          <div className="divide-y divide-[rgba(255,255,255,0.04)]">
            {recentReports.length === 0 ? (
              <div className="p-12 text-center">
                <div className="w-14 h-14 rounded-2xl bg-[rgba(255,255,255,0.03)] flex items-center justify-center mx-auto mb-4">
                  <svg className="w-7 h-7 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <p className="text-[var(--muted)] mb-4">No scans yet</p>
                <Link href="/dashboard/reports/new" className="text-sm text-[var(--accent-2)] hover:underline">
                  Run your first scan →
                </Link>
              </div>
            ) : (
              recentReports.map((report) => (
                <Link 
                  key={report.id} 
                  href={`/dashboard/reports/${report.id}`}
                  className="flex items-center gap-4 p-4 hover:bg-[rgba(255,255,255,0.02)] transition-colors"
                >
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                    report.status !== 'COMPLETED' ? 'bg-[rgba(255,255,255,0.05)]' :
                    report.overallScore >= 80 ? 'bg-emerald-500/10' :
                    report.overallScore >= 60 ? 'bg-amber-500/10' : 'bg-red-500/10'
                  }`}>
                    {report.status === 'IN_PROGRESS' ? (
                      <svg className="w-4 h-4 text-blue-400 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                    ) : (
                      <span className={`text-sm font-bold ${
                        report.overallScore >= 80 ? 'text-emerald-400' :
                        report.overallScore >= 60 ? 'text-amber-400' : 'text-red-400'
                      }`}>{report.overallScore}</span>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm">{report.title}</div>
                    <div className="text-xs text-[var(--muted)]">
                      {new Date(report.createdAt).toLocaleDateString('en-US', { 
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' 
                      })}
                    </div>
                  </div>
                  {report.status === 'COMPLETED' && (report.criticalCount > 0 || report.highCount > 0) && (
                    <div className="flex items-center gap-2">
                      {report.criticalCount > 0 && (
                        <span className="px-2 py-0.5 text-xs font-medium rounded bg-red-950/50 text-red-400">
                          {report.criticalCount} critical
                        </span>
                      )}
                      {report.highCount > 0 && (
                        <span className="px-2 py-0.5 text-xs font-medium rounded bg-amber-950/40 text-amber-400">
                          {report.highCount} high
                        </span>
                      )}
                    </div>
                  )}
                  <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </Link>
              ))
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="space-y-4">
          <div className="dashboard-card p-5">
            <h3 className="font-semibold mb-4">Quick Actions</h3>
            <div className="space-y-2">
              <Link 
                href="/dashboard/reports/new" 
                className="flex items-center gap-3 p-3 rounded-xl bg-[rgba(255,255,255,0.02)] hover:bg-[rgba(139,11,16,0.1)] border border-transparent hover:border-[rgba(139,11,16,0.2)] transition-all group"
              >
                <div className="w-9 h-9 rounded-lg bg-[rgba(255,255,255,0.05)] group-hover:bg-[var(--accent)]/20 flex items-center justify-center transition-colors">
                  <svg className="w-4 h-4 text-[var(--muted)] group-hover:text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
                  </svg>
                </div>
                <div>
                  <div className="font-medium text-sm">Run Scan</div>
                  <div className="text-xs text-[var(--muted)]">Check your infrastructure</div>
                </div>
              </Link>
              <Link 
                href="/dashboard/findings" 
                className="flex items-center gap-3 p-3 rounded-xl bg-[rgba(255,255,255,0.02)] hover:bg-[rgba(139,11,16,0.1)] border border-transparent hover:border-[rgba(139,11,16,0.2)] transition-all group"
              >
                <div className="w-9 h-9 rounded-lg bg-[rgba(255,255,255,0.05)] group-hover:bg-[var(--accent)]/20 flex items-center justify-center transition-colors">
                  <svg className="w-4 h-4 text-[var(--muted)] group-hover:text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                </div>
                <div>
                  <div className="font-medium text-sm">Findings</div>
                  <div className="text-xs text-[var(--muted)]">View pipeline issues</div>
                </div>
              </Link>
              <Link 
                href="/dashboard/contracts" 
                className="flex items-center gap-3 p-3 rounded-xl bg-[rgba(255,255,255,0.02)] hover:bg-[rgba(139,11,16,0.1)] border border-transparent hover:border-[rgba(139,11,16,0.2)] transition-all group"
              >
                <div className="w-9 h-9 rounded-lg bg-[rgba(255,255,255,0.05)] group-hover:bg-[var(--accent)]/20 flex items-center justify-center transition-colors">
                  <svg className="w-4 h-4 text-[var(--muted)] group-hover:text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <div>
                  <div className="font-medium text-sm">Contracts</div>
                  <div className="text-xs text-[var(--muted)]">Define data SLAs</div>
                </div>
              </Link>
              <Link
                href="/dashboard/pipeline" 
                className="flex items-center gap-3 p-3 rounded-xl bg-[rgba(255,255,255,0.02)] hover:bg-[rgba(139,11,16,0.1)] border border-transparent hover:border-[rgba(139,11,16,0.2)] transition-all group"
              >
                <div className="w-9 h-9 rounded-lg bg-[rgba(255,255,255,0.05)] group-hover:bg-[var(--accent)]/20 flex items-center justify-center transition-colors">
                  <svg className="w-4 h-4 text-[var(--muted)] group-hover:text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                </div>
                <div>
                  <div className="font-medium text-sm">Pipeline</div>
                  <div className="text-xs text-[var(--muted)]">Configure data flow</div>
                </div>
              </Link>
            </div>
          </div>

          {/* Getting Started (show if no pipeline configured) */}
          {pipelineNodes.length === 0 && (
            <div className="dashboard-card p-5 border-dashed border-amber-500/30 bg-amber-500/5">
              <h3 className="font-semibold mb-2 text-amber-400">Get Started</h3>
              <p className="text-sm text-[var(--muted)] mb-4">
                Build your data pipeline to start scanning your data infrastructure.
              </p>
              <Link href="/dashboard/pipeline" className="btn btn-secondary w-full justify-center text-sm">
                Build Pipeline
              </Link>
            </div>
          )}

          {/* Scheduled Scans */}
          {scheduledScans.length > 0 && (
            <div className="dashboard-card p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold">Scheduled Scans</h3>
                <Link href="/dashboard/schedules" className="text-xs text-[var(--accent-2)] hover:underline">
                  Manage →
                </Link>
              </div>
              <div className="space-y-2">
                {scheduledScans.map((schedule: any) => (
                  <div key={schedule.id} className="flex items-center gap-3 p-2 rounded-lg bg-[rgba(255,255,255,0.02)]">
                    <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
                      <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{schedule.name}</div>
                      <div className="text-xs text-[var(--muted)]">
                        Next: {schedule.nextRunAt ? new Date(schedule.nextRunAt).toLocaleString('en-US', { 
                          month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' 
                        }) : 'Not scheduled'}
                      </div>
                    </div>
                    <div className={`w-2 h-2 rounded-full ${schedule.enabled ? 'bg-emerald-500' : 'bg-[var(--muted)]'}`} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
