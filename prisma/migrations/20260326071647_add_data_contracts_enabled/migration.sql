-- AlterTable
ALTER TABLE "PipelineStack" ADD COLUMN     "dataContractsEnabled" BOOLEAN NOT NULL DEFAULT false;

-- CreateTable
CREATE TABLE "PipelineDataContract" (
    "id" TEXT NOT NULL,
    "scope" TEXT NOT NULL,
    "scopeRef" TEXT NOT NULL,
    "ownerUser" TEXT,
    "ownerTeam" TEXT,
    "contactChannel" TEXT,
    "slaTier" TEXT,
    "expectedFreshnessMinutes" INTEGER,
    "expectedExtractionFrequencyMinutes" INTEGER,
    "alertPolicyJson" JSONB,
    "notes" TEXT,
    "schemaExpectations" JSONB,
    "qualityRules" JSONB,
    "overridesJson" JSONB,
    "isException" BOOLEAN NOT NULL DEFAULT false,
    "parentContractId" TEXT,
    "autoSynced" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "pipelineStackId" TEXT NOT NULL,

    CONSTRAINT "PipelineDataContract_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "PipelineDataContract_pipelineStackId_idx" ON "PipelineDataContract"("pipelineStackId");

-- CreateIndex
CREATE INDEX "PipelineDataContract_parentContractId_idx" ON "PipelineDataContract"("parentContractId");

-- CreateIndex
CREATE UNIQUE INDEX "PipelineDataContract_pipelineStackId_scope_scopeRef_key" ON "PipelineDataContract"("pipelineStackId", "scope", "scopeRef");

-- AddForeignKey
ALTER TABLE "PipelineDataContract" ADD CONSTRAINT "PipelineDataContract_parentContractId_fkey" FOREIGN KEY ("parentContractId") REFERENCES "PipelineDataContract"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineDataContract" ADD CONSTRAINT "PipelineDataContract_pipelineStackId_fkey" FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE ON UPDATE CASCADE;
