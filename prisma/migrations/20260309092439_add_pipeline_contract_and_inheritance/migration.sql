-- AlterTable
ALTER TABLE "SourceContract" ADD COLUMN     "inheritFromPipeline" BOOLEAN NOT NULL DEFAULT true,
ADD COLUMN     "overridesJson" JSONB,
ADD COLUMN     "pipelineStackId" TEXT;

-- CreateTable
CREATE TABLE "PipelineContract" (
    "id" TEXT NOT NULL,
    "ownerUser" TEXT,
    "ownerTeam" TEXT,
    "contactChannel" TEXT,
    "slaTier" TEXT,
    "expectedFreshnessMinutes" INTEGER,
    "expectedExtractionFrequencyMinutes" INTEGER,
    "alertPolicyJson" JSONB,
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "pipelineStackId" TEXT NOT NULL,

    CONSTRAINT "PipelineContract_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "PipelineContract_pipelineStackId_key" ON "PipelineContract"("pipelineStackId");

-- CreateIndex
CREATE INDEX "PipelineContract_pipelineStackId_idx" ON "PipelineContract"("pipelineStackId");

-- CreateIndex
CREATE INDEX "SourceContract_pipelineStackId_idx" ON "SourceContract"("pipelineStackId");

-- AddForeignKey
ALTER TABLE "SourceContract" ADD CONSTRAINT "SourceContract_pipelineStackId_fkey" FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineContract" ADD CONSTRAINT "PipelineContract_pipelineStackId_fkey" FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE ON UPDATE CASCADE;
