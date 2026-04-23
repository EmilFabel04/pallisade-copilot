-- AlterTable
ALTER TABLE "MonitorGroup" ADD COLUMN     "monitoringPlanId" TEXT;

-- CreateTable
CREATE TABLE "MonitoringPlan" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "scopeType" TEXT NOT NULL,
    "scopeConfig" JSONB,
    "anchorFqn" TEXT,
    "anchorNodeId" TEXT,
    "mode" TEXT NOT NULL,
    "families" TEXT[],
    "totalAssets" INTEGER NOT NULL DEFAULT 0,
    "totalMonitors" INTEGER NOT NULL DEFAULT 0,
    "coveragePct" DOUBLE PRECISION,
    "healthScore" DOUBLE PRECISION,
    "healthStatus" TEXT,
    "passCount" INTEGER NOT NULL DEFAULT 0,
    "warnCount" INTEGER NOT NULL DEFAULT 0,
    "failCount" INTEGER NOT NULL DEFAULT 0,
    "errorCount" INTEGER NOT NULL DEFAULT 0,
    "lastAggregatedAt" TIMESTAMP(3),
    "schedule" TEXT,
    "timezone" TEXT DEFAULT 'UTC',
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "alertChannels" TEXT[],
    "alertOnStatus" TEXT[],
    "createdBy" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "MonitoringPlan_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "MonitoringPlan_organizationId_idx" ON "MonitoringPlan"("organizationId");

-- CreateIndex
CREATE INDEX "MonitoringPlan_enabled_idx" ON "MonitoringPlan"("enabled");

-- CreateIndex
CREATE INDEX "MonitorGroup_monitoringPlanId_idx" ON "MonitorGroup"("monitoringPlanId");

-- AddForeignKey
ALTER TABLE "MonitorGroup" ADD CONSTRAINT "MonitorGroup_monitoringPlanId_fkey" FOREIGN KEY ("monitoringPlanId") REFERENCES "MonitoringPlan"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MonitoringPlan" ADD CONSTRAINT "MonitoringPlan_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;
