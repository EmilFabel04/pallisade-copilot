import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

/**
 * Built-in policy profiles — seeded on first access.
 * These cannot be deleted by users.
 */
const BUILTIN_PROFILES = [
  {
    name: 'Critical SLA',
    description: 'Tight monitoring for business-critical assets',
    criticality: 'critical',
    freshnessConfig: { enabled: true, maxHours: 2, warningHours: 1 },
    schemaConfig: { enabled: true, strictness: 'strict', allowEvolution: false },
    volumeConfig: { enabled: true, growthRateThreshold: 0.05, minRows: 1 },
    anomalyConfig: { enabled: true, sensitivity: 0.99, lookbackDays: 30 },
    qualityConfig: { enabled: true, maxNullRate: 0.01, maxDuplicateRate: 0.005 },
    ingestionConfig: { syncLagToleranceMinutes: 15, failureTolerance: 'strict', schemaDriftStrictness: 'strict' },
    biConfig: { freshnessHours: 2, contentHealthEnabled: true, upstreamBreakStrictness: 'strict' },
    orchestrationConfig: { runLatencyMinutes: 15, scheduleLagMinutes: 5, failureTolerance: 'strict' },
    transformConfig: { testFailureTolerance: 'strict', modelFreshnessHours: 2 },
  },
  {
    name: 'Standard',
    description: 'Balanced monitoring for standard-priority assets',
    criticality: 'medium',
    freshnessConfig: { enabled: true, maxHours: 12, warningHours: 6 },
    schemaConfig: { enabled: true, strictness: 'warn', allowEvolution: true },
    volumeConfig: { enabled: true, growthRateThreshold: 0.15, minRows: 1 },
    anomalyConfig: { enabled: true, sensitivity: 0.95, lookbackDays: 14 },
    qualityConfig: { enabled: true, maxNullRate: 0.05, maxDuplicateRate: 0.02 },
    ingestionConfig: { syncLagToleranceMinutes: 60, failureTolerance: 'normal', schemaDriftStrictness: 'warn' },
    biConfig: { freshnessHours: 6, contentHealthEnabled: true, upstreamBreakStrictness: 'warn' },
    orchestrationConfig: { runLatencyMinutes: 30, scheduleLagMinutes: 15, failureTolerance: 'normal' },
    transformConfig: { testFailureTolerance: 'normal', modelFreshnessHours: 12 },
  },
  {
    name: 'Relaxed',
    description: 'Lenient monitoring for low-priority assets',
    criticality: 'low',
    freshnessConfig: { enabled: true, maxHours: 48, warningHours: 24 },
    schemaConfig: { enabled: false, strictness: 'ignore', allowEvolution: true },
    volumeConfig: { enabled: false },
    anomalyConfig: { enabled: false },
    qualityConfig: { enabled: true, maxNullRate: 0.10, maxDuplicateRate: 0.05 },
    ingestionConfig: { syncLagToleranceMinutes: 180, failureTolerance: 'relaxed', schemaDriftStrictness: 'ignore' },
    biConfig: { freshnessHours: 24, contentHealthEnabled: false, upstreamBreakStrictness: 'ignore' },
    orchestrationConfig: { runLatencyMinutes: 60, scheduleLagMinutes: 30, failureTolerance: 'relaxed' },
    transformConfig: { testFailureTolerance: 'relaxed', modelFreshnessHours: 48 },
  },
  {
    name: 'BI Shield',
    description: 'Optimized for BI/reporting assets — freshness and upstream integrity focus',
    targetDomain: 'bi',
    freshnessConfig: { enabled: true, maxHours: 6, warningHours: 4 },
    biConfig: { freshnessHours: 4, contentHealthEnabled: true, upstreamBreakStrictness: 'strict' },
  },
  {
    name: 'Source Guard',
    description: 'Optimized for ingestion assets — sync lag and schema drift focus',
    targetDomain: 'ingestion',
    freshnessConfig: { enabled: true, maxHours: 4, warningHours: 2 },
    ingestionConfig: { syncLagToleranceMinutes: 30, failureTolerance: 'strict', schemaDriftStrictness: 'strict' },
  },
];

// POST /api/schedule/policies/seed — Seed built-in profiles for the org
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) {
      return NextResponse.json({ error: 'No organization found' }, { status: 400 });
    }

    let created = 0;
    let skipped = 0;

    for (const profile of BUILTIN_PROFILES) {
      try {
        await prisma.policyProfile.upsert({
          where: {
            organizationId_name: {
              organizationId,
              name: profile.name,
            },
          },
          create: {
            organizationId,
            isBuiltIn: true,
            ...profile,
          },
          update: {
            // Update config fields on existing built-ins (keeps them fresh)
            isBuiltIn: true,
            description: profile.description,
            targetDomain: profile.targetDomain || null,
            criticality: profile.criticality || null,
            freshnessConfig: profile.freshnessConfig || undefined,
            schemaConfig: profile.schemaConfig || undefined,
            volumeConfig: profile.volumeConfig || undefined,
            anomalyConfig: profile.anomalyConfig || undefined,
            qualityConfig: profile.qualityConfig || undefined,
            ingestionConfig: profile.ingestionConfig || undefined,
            biConfig: profile.biConfig || undefined,
            orchestrationConfig: profile.orchestrationConfig || undefined,
            transformConfig: profile.transformConfig || undefined,
          },
        });
        created++;
      } catch {
        skipped++;
      }
    }

    return NextResponse.json({
      message: `Seeded ${created} built-in profiles (${skipped} skipped)`,
      created,
      skipped,
    });
  } catch (error: any) {
    console.error('[Policies] Error seeding profiles:', error);
    return NextResponse.json({ error: error.message || 'Failed to seed profiles' }, { status: 500 });
  }
}
