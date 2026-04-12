-- AlterTable
ALTER TABLE "MonitorGroup" ADD COLUMN     "presetGroupId" TEXT,
ADD COLUMN     "presetKey" TEXT;

-- CreateIndex
CREATE INDEX "MonitorGroup_presetGroupId_idx" ON "MonitorGroup"("presetGroupId");
