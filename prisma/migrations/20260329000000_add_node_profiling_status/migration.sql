-- CreateEnum
CREATE TYPE "ProfilingStatusEnum" AS ENUM ('pending', 'learning', 'ready', 'insufficient_data', 'recalibrating');

-- CreateTable
CREATE TABLE "NodeProfilingStatus" (
    "id" TEXT NOT NULL,
    "nodeFqn" TEXT NOT NULL,
    "pipelineId" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "status" "ProfilingStatusEnum" NOT NULL DEFAULT 'pending',
    "confidence" INTEGER NOT NULL DEFAULT 0,
    "sampleCount" INTEGER NOT NULL DEFAULT 0,
    "calendarDays" INTEGER NOT NULL DEFAULT 0,
    "firstObservedAt" TIMESTAMP(3),
    "lastProfiledAt" TIMESTAMP(3),
    "driftDetectedAt" TIMESTAMP(3),
    "driftCooldownUntil" TIMESTAMP(3),
    "dimensions" JSONB NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "NodeProfilingStatus_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "NodeProfilingStatus_pipelineId_idx" ON "NodeProfilingStatus"("pipelineId");

-- CreateIndex
CREATE INDEX "NodeProfilingStatus_organizationId_status_idx" ON "NodeProfilingStatus"("organizationId", "status");

-- CreateIndex
CREATE UNIQUE INDEX "NodeProfilingStatus_organizationId_nodeFqn_key" ON "NodeProfilingStatus"("organizationId", "nodeFqn");

-- AddForeignKey
ALTER TABLE "NodeProfilingStatus" ADD CONSTRAINT "NodeProfilingStatus_pipelineId_fkey" FOREIGN KEY ("pipelineId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "NodeProfilingStatus" ADD CONSTRAINT "NodeProfilingStatus_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;
