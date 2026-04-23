-- AlterTable
ALTER TABLE "Monitor" ADD COLUMN     "monitorGroupId" TEXT;

-- CreateTable
CREATE TABLE "MonitorGroup" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "groupType" TEXT NOT NULL,
    "anchorFqn" TEXT,
    "anchorNodeId" TEXT,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "schedule" TEXT,
    "timezone" TEXT DEFAULT 'UTC',
    "alertChannels" TEXT[],
    "alertOnStatus" TEXT[],
    "alertConfig" JSONB,
    "lastStatus" "MonitorRunStatus",
    "lastRunAt" TIMESTAMP(3),
    "organizationId" TEXT NOT NULL,
    "createdBy" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "MonitorGroup_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "MonitorGroup_organizationId_idx" ON "MonitorGroup"("organizationId");

-- CreateIndex
CREATE INDEX "MonitorGroup_groupType_idx" ON "MonitorGroup"("groupType");

-- CreateIndex
CREATE INDEX "MonitorGroup_anchorFqn_idx" ON "MonitorGroup"("anchorFqn");

-- CreateIndex
CREATE INDEX "Monitor_monitorGroupId_idx" ON "Monitor"("monitorGroupId");

-- AddForeignKey
ALTER TABLE "Monitor" ADD CONSTRAINT "Monitor_monitorGroupId_fkey" FOREIGN KEY ("monitorGroupId") REFERENCES "MonitorGroup"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MonitorGroup" ADD CONSTRAINT "MonitorGroup_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;
