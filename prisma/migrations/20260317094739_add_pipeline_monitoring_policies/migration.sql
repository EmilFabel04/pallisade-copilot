-- CreateTable
CREATE TABLE "PolicyProfile" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "isBuiltIn" BOOLEAN NOT NULL DEFAULT false,
    "targetDomain" TEXT,
    "criticality" TEXT,
    "freshnessConfig" JSONB,
    "schemaConfig" JSONB,
    "volumeConfig" JSONB,
    "anomalyConfig" JSONB,
    "qualityConfig" JSONB,
    "ingestionConfig" JSONB,
    "biConfig" JSONB,
    "orchestrationConfig" JSONB,
    "transformConfig" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "PolicyProfile_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PolicyAssignment" (
    "id" TEXT NOT NULL,
    "profileId" TEXT NOT NULL,
    "nodeFqn" TEXT,
    "nodeDomain" TEXT,
    "nodeCriticality" TEXT,
    "branchRootFqn" TEXT,
    "assignmentType" TEXT NOT NULL,
    "overrides" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "PolicyAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "PolicyProfile_organizationId_idx" ON "PolicyProfile"("organizationId");

-- CreateIndex
CREATE UNIQUE INDEX "PolicyProfile_organizationId_name_key" ON "PolicyProfile"("organizationId", "name");

-- CreateIndex
CREATE INDEX "PolicyAssignment_organizationId_idx" ON "PolicyAssignment"("organizationId");

-- CreateIndex
CREATE INDEX "PolicyAssignment_nodeFqn_idx" ON "PolicyAssignment"("nodeFqn");

-- CreateIndex
CREATE INDEX "PolicyAssignment_nodeDomain_idx" ON "PolicyAssignment"("nodeDomain");

-- CreateIndex
CREATE INDEX "PolicyAssignment_branchRootFqn_idx" ON "PolicyAssignment"("branchRootFqn");

-- CreateIndex
CREATE UNIQUE INDEX "PolicyAssignment_organizationId_assignmentType_nodeFqn_key" ON "PolicyAssignment"("organizationId", "assignmentType", "nodeFqn");

-- CreateIndex
CREATE UNIQUE INDEX "PolicyAssignment_organizationId_assignmentType_branchRootFq_key" ON "PolicyAssignment"("organizationId", "assignmentType", "branchRootFqn");

-- CreateIndex
CREATE UNIQUE INDEX "PolicyAssignment_organizationId_assignmentType_nodeDomain_n_key" ON "PolicyAssignment"("organizationId", "assignmentType", "nodeDomain", "nodeCriticality");

-- AddForeignKey
ALTER TABLE "PolicyProfile" ADD CONSTRAINT "PolicyProfile_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PolicyAssignment" ADD CONSTRAINT "PolicyAssignment_profileId_fkey" FOREIGN KEY ("profileId") REFERENCES "PolicyProfile"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PolicyAssignment" ADD CONSTRAINT "PolicyAssignment_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;
