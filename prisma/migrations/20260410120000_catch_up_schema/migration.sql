-- AlterEnum
BEGIN;
CREATE TYPE "IntegrationType_new" AS ENUM ('SNOWFLAKE', 'BIGQUERY', 'POSTGRES', 'REDSHIFT', 'SQLSERVER', 'AZURE_SQL', 'AZURE_SYNAPSE', 'FIVETRAN', 'AIRBYTE', 'STITCH', 'DBT_CLOUD', 'DBT_CORE', 'AIRFLOW', 'DAGSTER', 'PREFECT', 'N8N', 'TABLEAU', 'LOOKER', 'POWERBI', 'METABASE', 'DATABRICKS', 'AMAZON_S3', 'GCS', 'ADLS', 'GITHUB', 'GITLAB', 'BITBUCKET', 'SLACK', 'PAGERDUTY', 'OPSGENIE', 'TEAMS', 'LINUX_SERVER', 'JIRA', 'CUSTOM_WEBHOOK');
ALTER TABLE "Integration" ALTER COLUMN "type" TYPE "IntegrationType_new" USING ("type"::text::"IntegrationType_new");
ALTER TYPE "IntegrationType" RENAME TO "IntegrationType_old";
ALTER TYPE "IntegrationType_new" RENAME TO "IntegrationType";
DROP TYPE "IntegrationType_old";
COMMIT;

-- DropForeignKey
ALTER TABLE "NodeProfilingStatus" DROP CONSTRAINT "NodeProfilingStatus_organizationId_fkey";

-- DropForeignKey
ALTER TABLE "NodeProfilingStatus" DROP CONSTRAINT "NodeProfilingStatus_pipelineId_fkey";

-- AlterTable
ALTER TABLE "Organization" ADD COLUMN     "slaDiscoveryNodeLimit" INTEGER NOT NULL DEFAULT 100;

-- AlterTable
ALTER TABLE "PipelineDataContract" ADD COLUMN     "anomalyConfig" JSONB,
ADD COLUMN     "archivedAt" TIMESTAMP(3),
ADD COLUMN     "biConfig" JSONB,
ADD COLUMN     "freshnessConfig" JSONB,
ADD COLUMN     "ingestionConfig" JSONB,
ADD COLUMN     "name" TEXT,
ADD COLUMN     "nodeFqns" JSONB,
ADD COLUMN     "orchestrationConfig" JSONB,
ADD COLUMN     "qualityConfig" JSONB,
ADD COLUMN     "schemaConfig" JSONB,
ADD COLUMN     "status" TEXT NOT NULL DEFAULT 'active',
ADD COLUMN     "transformConfig" JSONB,
ADD COLUMN     "volumeConfig" JSONB;

-- AlterTable
ALTER TABLE "PipelineStack" ADD COLUMN     "contractAllowOverrides" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "contractViolationAlerting" BOOLEAN NOT NULL DEFAULT true;

-- AlterTable
ALTER TABLE "PolicyAssignment" ADD COLUMN     "archivedAt" TIMESTAMP(3),
ADD COLUMN     "status" TEXT NOT NULL DEFAULT 'active';

-- DropTable
DROP TABLE "NodeProfilingStatus";

-- DropEnum
DROP TYPE "Priority";

-- DropEnum
DROP TYPE "ProfilingStatusEnum";

-- CreateTable
CREATE TABLE "DriftRecommendation" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "monitorId" TEXT NOT NULL,
    "monitorName" TEXT NOT NULL,
    "monitorType" TEXT NOT NULL,
    "targetFqn" TEXT NOT NULL,
    "driftCategory" TEXT NOT NULL,
    "severity" TEXT NOT NULL,
    "currentField" TEXT NOT NULL,
    "currentValue" TEXT NOT NULL,
    "recommendedValue" TEXT NOT NULL,
    "reasoning" TEXT NOT NULL,
    "confidence" DOUBLE PRECISION NOT NULL,
    "evidence" JSONB NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "reviewedAt" TIMESTAMP(3),
    "runId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "DriftRecommendation_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "DriftRecommendation_organizationId_status_idx" ON "DriftRecommendation"("organizationId", "status");

-- CreateIndex
CREATE INDEX "DriftRecommendation_monitorId_idx" ON "DriftRecommendation"("monitorId");

-- CreateIndex
CREATE INDEX "DriftRecommendation_runId_idx" ON "DriftRecommendation"("runId");

-- AddForeignKey
ALTER TABLE "DriftRecommendation" ADD CONSTRAINT "DriftRecommendation_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DriftRecommendation" ADD CONSTRAINT "DriftRecommendation_monitorId_fkey" FOREIGN KEY ("monitorId") REFERENCES "Monitor"("id") ON DELETE CASCADE ON UPDATE CASCADE;

