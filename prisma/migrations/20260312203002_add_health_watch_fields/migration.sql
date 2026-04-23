-- AlterEnum
-- This migration adds more than one value to an enum.
-- With PostgreSQL versions 11 and earlier, this is not possible
-- in a single migration. This can be worked around by creating
-- multiple migrations, each migration adding only one value to
-- the enum.


ALTER TYPE "MonitorKind" ADD VALUE 'BI_FRESHNESS_PROXY';
ALTER TYPE "MonitorKind" ADD VALUE 'BI_UPSTREAM_BREAK_RISK';
ALTER TYPE "MonitorKind" ADD VALUE 'BI_CONTENT_HEALTH';
ALTER TYPE "MonitorKind" ADD VALUE 'BI_REFRESH_FAILURE';
ALTER TYPE "MonitorKind" ADD VALUE 'BI_LOGIC_VALIDATION';

-- AlterTable
ALTER TABLE "MonitorGroup" ADD COLUMN     "anchorNodeType" TEXT,
ADD COLUMN     "anchorPlatform" TEXT,
ADD COLUMN     "coveragePct" DOUBLE PRECISION,
ADD COLUMN     "healthDetails" JSONB,
ADD COLUMN     "healthScore" DOUBLE PRECISION,
ADD COLUMN     "lastHealthAt" TIMESTAMP(3),
ADD COLUMN     "scopeConfig" JSONB,
ADD COLUMN     "watchType" TEXT;

-- CreateIndex
CREATE INDEX "MonitorGroup_watchType_idx" ON "MonitorGroup"("watchType");
