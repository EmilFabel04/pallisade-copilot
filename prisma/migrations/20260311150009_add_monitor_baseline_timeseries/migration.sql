-- AlterTable
ALTER TABLE "Monitor" ADD COLUMN     "lastAlertAt" TIMESTAMP(3),
ADD COLUMN     "lastAlertStatus" TEXT;

-- CreateTable
CREATE TABLE "MonitorBaseline" (
    "id" TEXT NOT NULL,
    "metricName" TEXT NOT NULL,
    "metricValue" DOUBLE PRECISION NOT NULL,
    "measuredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "dayOfWeek" INTEGER,
    "hourOfDay" INTEGER,
    "targetFqn" TEXT,
    "details" JSONB,
    "monitorId" TEXT NOT NULL,

    CONSTRAINT "MonitorBaseline_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "MonitorBaseline_monitorId_metricName_measuredAt_idx" ON "MonitorBaseline"("monitorId", "metricName", "measuredAt");

-- CreateIndex
CREATE INDEX "MonitorBaseline_monitorId_metricName_dayOfWeek_idx" ON "MonitorBaseline"("monitorId", "metricName", "dayOfWeek");

-- CreateIndex
CREATE INDEX "MonitorBaseline_measuredAt_idx" ON "MonitorBaseline"("measuredAt");

-- AddForeignKey
ALTER TABLE "MonitorBaseline" ADD CONSTRAINT "MonitorBaseline_monitorId_fkey" FOREIGN KEY ("monitorId") REFERENCES "Monitor"("id") ON DELETE CASCADE ON UPDATE CASCADE;
