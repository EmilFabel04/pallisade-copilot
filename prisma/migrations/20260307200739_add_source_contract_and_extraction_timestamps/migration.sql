-- AlterTable
ALTER TABLE "Integration" ADD COLUMN     "lastExtractedAt" TIMESTAMP(3),
ADD COLUMN     "lastLineageExtractedAt" TIMESTAMP(3),
ADD COLUMN     "lastLogsExtractedAt" TIMESTAMP(3),
ADD COLUMN     "lastSchemaExtractedAt" TIMESTAMP(3);

-- CreateTable
CREATE TABLE "SourceContract" (
    "id" TEXT NOT NULL,
    "ownerUser" TEXT,
    "ownerTeam" TEXT,
    "contactChannel" TEXT,
    "slaTier" TEXT,
    "expectedFreshnessMinutes" INTEGER,
    "expectedExtractionFrequencyMinutes" INTEGER,
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "integrationId" TEXT NOT NULL,

    CONSTRAINT "SourceContract_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "SourceContract_integrationId_key" ON "SourceContract"("integrationId");

-- CreateIndex
CREATE INDEX "SourceContract_integrationId_idx" ON "SourceContract"("integrationId");

-- AddForeignKey
ALTER TABLE "SourceContract" ADD CONSTRAINT "SourceContract_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE CASCADE ON UPDATE CASCADE;
