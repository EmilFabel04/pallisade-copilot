-- CreateEnum
CREATE TYPE "TeamRole" AS ENUM ('OWNER', 'ADMIN', 'MANAGER', 'ENGINEER', 'VIEWER');

-- CreateEnum
CREATE TYPE "MemberStatus" AS ENUM ('ACTIVE', 'INACTIVE', 'SUSPENDED');

-- CreateEnum
CREATE TYPE "InviteStatus" AS ENUM ('PENDING', 'ACCEPTED', 'DECLINED', 'EXPIRED', 'REVOKED');

-- CreateEnum
CREATE TYPE "OnboardingStatus" AS ENUM ('NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'NEEDS_UPDATE');

-- CreateEnum
CREATE TYPE "PipelineAccessLevel" AS ENUM ('OWNER', 'EDITOR', 'VIEWER');

-- CreateEnum
CREATE TYPE "PipelineStackStatus" AS ENUM ('DRAFT', 'CONFIGURING', 'READY', 'SCANNING', 'ERROR');

-- CreateEnum
CREATE TYPE "PipelineLayer" AS ENUM ('INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'STORAGE', 'VERSION_CONTROL', 'ORCHESTRATION', 'INFRASTRUCTURE');

-- CreateEnum
CREATE TYPE "PipelineNodeStatus" AS ENUM ('PENDING', 'TESTING', 'CONNECTED', 'HEALTHY', 'WARNING', 'ERROR');

-- CreateEnum
CREATE TYPE "PipelineScanStatus" AS ENUM ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED');

-- CreateEnum
CREATE TYPE "ContractStatus" AS ENUM ('DRAFT', 'ACTIVE', 'VIOLATED', 'DEPRECATED');

-- CreateEnum
CREATE TYPE "DataTier" AS ENUM ('GOLD', 'SILVER', 'BRONZE');

-- CreateEnum
CREATE TYPE "SLOTier" AS ENUM ('REALTIME', 'HOURLY', 'STANDARD', 'DAILY', 'WEEKLY', 'CUSTOM');

-- CreateEnum
CREATE TYPE "Criticality" AS ENUM ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW');

-- CreateEnum
CREATE TYPE "Plan" AS ENUM ('STARTER', 'PROFESSIONAL', 'ENTERPRISE');

-- CreateEnum
CREATE TYPE "ReportType" AS ENUM ('PERIMETER_SECURITY', 'SAAS_IDENTITY', 'CLOUD_RECOVERY', 'DATA_FRESHNESS', 'DATA_QUALITY', 'SCHEMA_DRIFT', 'DATA_INTEGRITY', 'DATA_ANOMALY', 'PIPELINE_HEALTH', 'TEST_COVERAGE', 'AI_READINESS', 'FUSION_BUNDLE');

-- CreateEnum
CREATE TYPE "ReportStatus" AS ENUM ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED');

-- CreateEnum
CREATE TYPE "RemediationStatus" AS ENUM ('NOT_STARTED', 'IN_PROGRESS', 'ON_HOLD', 'COMPLETED', 'OVERDUE');

-- CreateEnum
CREATE TYPE "Priority" AS ENUM ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW');

-- CreateEnum
CREATE TYPE "TaskStatus" AS ENUM ('TODO', 'IN_PROGRESS', 'BLOCKED', 'COMPLETED', 'CANCELLED');

-- CreateEnum
CREATE TYPE "TaskCategory" AS ENUM ('GENERAL', 'SECURITY_FIX', 'CONFIGURATION', 'DOCUMENTATION', 'REVIEW', 'DEPLOYMENT');

-- CreateEnum
CREATE TYPE "MessageRole" AS ENUM ('USER', 'ASSISTANT', 'SYSTEM');

-- CreateEnum
CREATE TYPE "CopilotContextType" AS ENUM ('GENERAL', 'PIPELINE', 'DEBUGGING', 'BUILDING');

-- CreateEnum
CREATE TYPE "DebugStatus" AS ENUM ('INVESTIGATING', 'ROOT_CAUSE_FOUND', 'FIXING', 'RESOLVED', 'WONT_FIX');

-- CreateEnum
CREATE TYPE "NotificationType" AS ENUM ('REPORT_READY', 'TASK_DUE', 'PLAN_UPDATE', 'SECURITY_ALERT', 'SYSTEM');

-- CreateEnum
CREATE TYPE "AppliedFixStatus" AS ENUM ('PENDING', 'MERGED', 'CLOSED', 'FAILED');

-- CreateEnum
CREATE TYPE "ChangePlanStatus" AS ENUM ('DRAFT', 'VALIDATING', 'VALIDATED', 'APPLYING', 'APPLIED', 'FAILED', 'REJECTED');

-- CreateEnum
CREATE TYPE "FixOutcomeStatus" AS ENUM ('PENDING', 'RESOLVED', 'PARTIALLY_RESOLVED', 'UNRESOLVED', 'REGRESSED', 'UNKNOWN');

-- CreateEnum
CREATE TYPE "OutcomeDetectionMethod" AS ENUM ('AUTOMATIC', 'USER_CONFIRMED', 'PR_MERGED', 'TIMEOUT');

-- CreateEnum
CREATE TYPE "IntegrationType" AS ENUM ('SNOWFLAKE', 'BIGQUERY', 'POSTGRES', 'REDSHIFT', 'SQLSERVER', 'AZURE_SQL', 'AZURE_SYNAPSE', 'FIVETRAN', 'AIRBYTE', 'STITCH', 'DBT_CLOUD', 'DBT_CORE', 'AIRFLOW', 'DAGSTER', 'PREFECT', 'N8N', 'TABLEAU', 'LOOKER', 'POWERBI', 'METABASE', 'ELEMENTARY', 'MONTE_CARLO', 'BIGEYE', 'SODA', 'DATABRICKS', 'AMAZON_S3', 'GCS', 'ADLS', 'GITHUB', 'GITLAB', 'BITBUCKET', 'SLACK', 'PAGERDUTY', 'OPSGENIE', 'TEAMS', 'LINUX_SERVER', 'JIRA', 'CUSTOM_WEBHOOK');

-- CreateEnum
CREATE TYPE "IntegrationStatus" AS ENUM ('ACTIVE', 'INACTIVE', 'ERROR');

-- CreateEnum
CREATE TYPE "WorkflowStatus" AS ENUM ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED');

-- CreateEnum
CREATE TYPE "MetricType" AS ENUM ('NULL_RATE', 'DISTINCT_COUNT', 'DISTINCT_RATE', 'MIN_VALUE', 'MAX_VALUE', 'AVG_VALUE', 'SUM_VALUE', 'STDDEV', 'ROW_COUNT', 'FRESHNESS_HOURS', 'SIZE_BYTES', 'DUPLICATE_RATE', 'EMPTY_STRING_RATE', 'OUTLIER_COUNT', 'CUSTOM');

-- CreateEnum
CREATE TYPE "RiskAPIPlan" AS ENUM ('STARTER', 'STANDARD', 'PROFESSIONAL', 'ENTERPRISE');

-- CreateEnum
CREATE TYPE "RiskAPIStatus" AS ENUM ('ACTIVE', 'SUSPENDED', 'CANCELLED', 'TRIAL');

-- CreateEnum
CREATE TYPE "OverrideDecision" AS ENUM ('APPROVE', 'DENY');

-- CreateEnum
CREATE TYPE "FindingSeverity" AS ENUM ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO');

-- CreateEnum
CREATE TYPE "FindingStatus" AS ENUM ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'WONT_FIX', 'FALSE_POSITIVE', 'ACCEPTED_RISK', 'SUPPRESSED');

-- CreateEnum
CREATE TYPE "ResponseType" AS ENUM ('FIXED', 'ACKNOWLEDGED', 'FALSE_POSITIVE', 'ACCEPTED_RISK', 'WONT_FIX', 'EXPECTED_BEHAVIOR', 'NEEDS_REVIEW');

-- CreateEnum
CREATE TYPE "RuleAction" AS ENUM ('SUPPRESS', 'REDUCE_SEVERITY', 'AUTO_ACKNOWLEDGE', 'FLAG_FOR_REVIEW');

-- CreateEnum
CREATE TYPE "PatternType" AS ENUM ('COLUMN_CORRELATION', 'TIME_SNAPSHOT', 'SCD_VERSIONING', 'FOREIGN_KEY', 'GROUPING_KEY', 'EXPECTED_NULL', 'EXPECTED_OUTLIER', 'SEASONAL_PATTERN', 'CUSTOM');

-- CreateEnum
CREATE TYPE "PatternRuleStatus" AS ENUM ('PENDING', 'CONFIRMED', 'REJECTED', 'AUTO_CONFIRMED');

-- CreateEnum
CREATE TYPE "PatternRuleAction" AS ENUM ('SUPPRESSED', 'NEEDS_CONFIRMATION', 'FLAGGED');

-- CreateEnum
CREATE TYPE "ArtifactType" AS ENUM ('QUERY', 'FIX', 'INSIGHT', 'CODE', 'PLAN');

-- CreateEnum
CREATE TYPE "MonitorKind" AS ENUM ('FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_RATE', 'UNIQUENESS', 'DISTRIBUTION', 'REFERENTIAL', 'CUSTOM_SQL', 'ANOMALY', 'CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS', 'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT', 'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE', 'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS');

-- CreateEnum
CREATE TYPE "MonitorRunStatus" AS ENUM ('PASS', 'WARN', 'FAIL', 'ERROR', 'SKIPPED', 'RUNNING');

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "name" TEXT,
    "passwordHash" TEXT,
    "image" TEXT,
    "emailVerified" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Account" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "provider" TEXT NOT NULL,
    "providerAccountId" TEXT NOT NULL,
    "refresh_token" TEXT,
    "access_token" TEXT,
    "expires_at" INTEGER,
    "token_type" TEXT,
    "scope" TEXT,
    "id_token" TEXT,
    "session_state" TEXT,

    CONSTRAINT "Account_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Session" (
    "id" TEXT NOT NULL,
    "sessionToken" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "expires" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "VerificationToken" (
    "identifier" TEXT NOT NULL,
    "token" TEXT NOT NULL,
    "expires" TIMESTAMP(3) NOT NULL
);

-- CreateTable
CREATE TABLE "Organization" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "domain" TEXT,
    "logo" TEXT,
    "plan" "Plan" NOT NULL DEFAULT 'STARTER',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "sloDefaults" JSONB,
    "sloEnabled" BOOLEAN NOT NULL DEFAULT true,
    "alertOnSLOBreach" BOOLEAN NOT NULL DEFAULT true,

    CONSTRAINT "Organization_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TeamMember" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "role" "TeamRole" NOT NULL DEFAULT 'ENGINEER',
    "permissions" JSONB,
    "status" "MemberStatus" NOT NULL DEFAULT 'ACTIVE',
    "invitedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "joinedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "title" TEXT,
    "department" TEXT,
    "lastActiveAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "TeamMember_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TeamInvite" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "token" TEXT NOT NULL,
    "role" "TeamRole" NOT NULL DEFAULT 'ENGINEER',
    "personalNote" TEXT,
    "title" TEXT,
    "department" TEXT,
    "status" "InviteStatus" NOT NULL DEFAULT 'PENDING',
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "invitedById" TEXT,
    "inviterName" TEXT,
    "organizationId" TEXT NOT NULL,
    "emailSentAt" TIMESTAMP(3),
    "viewedAt" TIMESTAMP(3),
    "respondedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "TeamInvite_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PipelineStack" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "status" "PipelineStackStatus" NOT NULL DEFAULT 'DRAFT',
    "healthScore" DOUBLE PRECISION,
    "lastScanAt" TIMESTAMP(3),
    "tokenLimitMonthly" INTEGER,
    "tokensUsedThisMonth" INTEGER NOT NULL DEFAULT 0,
    "tokenResetDate" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "createdById" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "PipelineStack_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PipelineContext" (
    "id" TEXT NOT NULL,
    "pipelineStackId" TEXT NOT NULL,
    "onboardingStatus" "OnboardingStatus" NOT NULL DEFAULT 'NOT_STARTED',
    "onboardingCompletedAt" TIMESTAMP(3),
    "environmentContext" JSONB,
    "integrationContexts" JSONB,
    "conventionsContext" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "PipelineContext_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PipelineAccess" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "pipelineId" TEXT NOT NULL,
    "accessLevel" "PipelineAccessLevel" NOT NULL DEFAULT 'VIEWER',
    "grantedBy" TEXT,
    "grantedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "tokensUsed" INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT "PipelineAccess_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PipelineNode" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "layer" "PipelineLayer" NOT NULL,
    "toolType" TEXT NOT NULL,
    "config" JSONB,
    "positionX" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "positionY" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "status" "PipelineNodeStatus" NOT NULL DEFAULT 'PENDING',
    "lastTestedAt" TIMESTAMP(3),
    "lastError" TEXT,
    "healthScore" DOUBLE PRECISION,
    "lastScanAt" TIMESTAMP(3),
    "findingsCount" INTEGER NOT NULL DEFAULT 0,
    "criticalCount" INTEGER NOT NULL DEFAULT 0,
    "highCount" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "stackId" TEXT NOT NULL,
    "integrationId" TEXT,

    CONSTRAINT "PipelineNode_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PipelineEdge" (
    "id" TEXT NOT NULL,
    "sourceId" TEXT NOT NULL,
    "targetId" TEXT NOT NULL,
    "label" TEXT,
    "dataFlow" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "stackId" TEXT NOT NULL,

    CONSTRAINT "PipelineEdge_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PipelineScan" (
    "id" TEXT NOT NULL,
    "status" "PipelineScanStatus" NOT NULL DEFAULT 'PENDING',
    "startedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),
    "durationMs" INTEGER,
    "totalFindings" INTEGER NOT NULL DEFAULT 0,
    "criticalCount" INTEGER NOT NULL DEFAULT 0,
    "highCount" INTEGER NOT NULL DEFAULT 0,
    "mediumCount" INTEGER NOT NULL DEFAULT 0,
    "lowCount" INTEGER NOT NULL DEFAULT 0,
    "healthScore" DOUBLE PRECISION,
    "layersScanned" TEXT[],
    "nodesScanned" INTEGER NOT NULL DEFAULT 0,
    "errorMessage" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "stackId" TEXT NOT NULL,

    CONSTRAINT "PipelineScan_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PipelineNodeFinding" (
    "id" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "severity" "FindingSeverity" NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "suggestedFix" JSONB,
    "rootCauseNodeId" TEXT,
    "rootCauseType" TEXT,
    "nodeId" TEXT NOT NULL,
    "scanId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PipelineNodeFinding_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DataContract" (
    "id" TEXT NOT NULL,
    "database" TEXT NOT NULL,
    "schema" TEXT NOT NULL DEFAULT 'public',
    "tableName" TEXT NOT NULL,
    "fullName" TEXT NOT NULL,
    "version" INTEGER NOT NULL DEFAULT 1,
    "status" "ContractStatus" NOT NULL DEFAULT 'DRAFT',
    "publishedAt" TIMESTAMP(3),
    "description" TEXT,
    "owner" TEXT,
    "ownerEmail" TEXT,
    "steward" TEXT,
    "tags" TEXT[],
    "businessDomain" TEXT,
    "dataTier" "DataTier" NOT NULL DEFAULT 'SILVER',
    "criticality" "Criticality" NOT NULL DEFAULT 'MEDIUM',
    "businessImpact" TEXT,
    "consumers" TEXT[],
    "stakeholders" TEXT[],
    "usedInReports" TEXT[],
    "freshnessEnabled" BOOLEAN NOT NULL DEFAULT true,
    "freshnessHours" INTEGER,
    "freshnessWarningHours" INTEGER,
    "timestampColumn" TEXT,
    "sloTier" "SLOTier" NOT NULL DEFAULT 'STANDARD',
    "qualityEnabled" BOOLEAN NOT NULL DEFAULT true,
    "maxNullRate" DOUBLE PRECISION,
    "maxDuplicateRate" DOUBLE PRECISION,
    "requiredColumns" TEXT[],
    "columnNullRules" JSONB,
    "schemaEnabled" BOOLEAN NOT NULL DEFAULT false,
    "expectedSchema" JSONB,
    "allowSchemaEvolution" BOOLEAN NOT NULL DEFAULT true,
    "volumeEnabled" BOOLEAN NOT NULL DEFAULT false,
    "minRowCount" INTEGER,
    "maxRowCount" INTEGER,
    "expectedGrowthRate" DOUBLE PRECISION,
    "slackChannel" TEXT,
    "pagerDutyService" TEXT,
    "emailRecipients" TEXT[],
    "alertOnWarning" BOOLEAN NOT NULL DEFAULT true,
    "alertOnViolation" BOOLEAN NOT NULL DEFAULT true,
    "alertCooldownMins" INTEGER NOT NULL DEFAULT 60,
    "complianceScore" DOUBLE PRECISION,
    "violationCount" INTEGER NOT NULL DEFAULT 0,
    "lastViolationAt" TIMESTAMP(3),
    "lastCheckAt" TIMESTAMP(3),
    "consecutivePasses" INTEGER NOT NULL DEFAULT 0,
    "downstreamCount" INTEGER,
    "downstreamCritical" INTEGER,
    "upstreamCount" INTEGER,
    "impactScore" DOUBLE PRECISION,
    "lastImpactUpdate" TIMESTAMP(3),
    "anomalyEnabled" BOOLEAN NOT NULL DEFAULT false,
    "historicalPatterns" JSONB,
    "anomalyThreshold" DOUBLE PRECISION DEFAULT 0.95,
    "lastMLUpdate" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,

    CONSTRAINT "DataContract_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ContractViolation" (
    "id" TEXT NOT NULL,
    "contractId" TEXT NOT NULL,
    "violationType" TEXT NOT NULL,
    "severity" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "details" JSONB,
    "resolvedAt" TIMESTAMP(3),
    "resolvedBy" TEXT,
    "resolution" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ContractViolation_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TableConfig" (
    "id" TEXT NOT NULL,
    "database" TEXT NOT NULL,
    "schema" TEXT NOT NULL DEFAULT 'public',
    "tableName" TEXT NOT NULL,
    "fullName" TEXT NOT NULL,
    "freshnessHours" INTEGER,
    "timestampColumn" TEXT,
    "sloTier" "SLOTier" NOT NULL DEFAULT 'STANDARD',
    "description" TEXT,
    "owner" TEXT,
    "criticality" "Criticality" NOT NULL DEFAULT 'MEDIUM',
    "tags" TEXT[],
    "businessDomain" TEXT,
    "dataTier" "DataTier" NOT NULL DEFAULT 'SILVER',
    "stakeholders" TEXT[],
    "usedInReports" TEXT[],
    "businessImpact" TEXT,
    "dataContract" JSONB,
    "slackChannel" TEXT,
    "pagerDutyService" TEXT,
    "downstreamCount" INTEGER,
    "downstreamCritical" INTEGER,
    "impactScore" DOUBLE PRECISION,
    "lastImpactUpdate" TIMESTAMP(3),
    "expectedRowCountMin" INTEGER,
    "expectedRowCountMax" INTEGER,
    "nullRateThreshold" DOUBLE PRECISION,
    "duplicateThreshold" DOUBLE PRECISION,
    "historicalPatterns" JSONB,
    "lastMLUpdate" TIMESTAMP(3),
    "anomalyThreshold" DOUBLE PRECISION DEFAULT 0.95,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,

    CONSTRAINT "TableConfig_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LineageNode" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "database" TEXT,
    "schema" TEXT,
    "tableName" TEXT NOT NULL,
    "nodeType" TEXT NOT NULL DEFAULT 'table',
    "platform" TEXT,
    "description" TEXT,
    "owner" TEXT,
    "tags" TEXT[],
    "criticality" "Criticality" NOT NULL DEFAULT 'MEDIUM',
    "businessDomain" TEXT,
    "rowCount" INTEGER,
    "lastUpdated" TIMESTAMP(3),
    "upstreamCount" INTEGER NOT NULL DEFAULT 0,
    "downstreamCount" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,

    CONSTRAINT "LineageNode_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LineageEdge" (
    "id" TEXT NOT NULL,
    "sourceId" TEXT NOT NULL,
    "targetId" TEXT NOT NULL,
    "edgeType" TEXT NOT NULL DEFAULT 'depends_on',
    "columns" TEXT[],
    "transformation" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "LineageEdge_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LineageSnapshot" (
    "id" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "dialect" TEXT NOT NULL,
    "nodeCount" INTEGER NOT NULL DEFAULT 0,
    "edgeCount" INTEGER NOT NULL DEFAULT 0,
    "rootCount" INTEGER NOT NULL DEFAULT 0,
    "leafCount" INTEGER NOT NULL DEFAULT 0,
    "graphData" JSONB,
    "status" TEXT NOT NULL DEFAULT 'building',
    "errorMessage" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,

    CONSTRAINT "LineageSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Report" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "type" "ReportType" NOT NULL,
    "status" "ReportStatus" NOT NULL DEFAULT 'PENDING',
    "packageSlug" TEXT NOT NULL,
    "overallScore" INTEGER,
    "criticalCount" INTEGER NOT NULL DEFAULT 0,
    "highCount" INTEGER NOT NULL DEFAULT 0,
    "mediumCount" INTEGER NOT NULL DEFAULT 0,
    "lowCount" INTEGER NOT NULL DEFAULT 0,
    "executiveSummary" TEXT,
    "findings" JSONB,
    "recommendations" JSONB,
    "rawData" JSONB,
    "pdfUrl" TEXT,
    "scanStartedAt" TIMESTAMP(3),
    "scanCompletedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "userId" TEXT NOT NULL,
    "organizationId" TEXT,

    CONSTRAINT "Report_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ScanSchedule" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "scanTypes" TEXT[],
    "tables" TEXT[],
    "cronExpression" TEXT NOT NULL,
    "timezone" TEXT NOT NULL DEFAULT 'UTC',
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "notifyOnSuccess" BOOLEAN NOT NULL DEFAULT false,
    "notifyOnFailure" BOOLEAN NOT NULL DEFAULT true,
    "notifyChannels" TEXT[],
    "emailRecipients" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "lastRunAt" TIMESTAMP(3),
    "lastRunStatus" TEXT,
    "lastRunReportId" TEXT,
    "nextRunAt" TIMESTAMP(3),
    "runCount" INTEGER NOT NULL DEFAULT 0,
    "failureCount" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,
    "createdById" TEXT,

    CONSTRAINT "ScanSchedule_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RemediationPlan" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT,
    "status" "RemediationStatus" NOT NULL DEFAULT 'NOT_STARTED',
    "priority" "Priority" NOT NULL DEFAULT 'MEDIUM',
    "startDate" TIMESTAMP(3),
    "targetDate" TIMESTAMP(3),
    "completedAt" TIMESTAMP(3),
    "progressPercent" INTEGER NOT NULL DEFAULT 0,
    "milestones" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "reportId" TEXT,
    "userId" TEXT NOT NULL,
    "organizationId" TEXT,

    CONSTRAINT "RemediationPlan_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Task" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT,
    "status" "TaskStatus" NOT NULL DEFAULT 'TODO',
    "priority" "Priority" NOT NULL DEFAULT 'MEDIUM',
    "dueDate" TIMESTAMP(3),
    "completedAt" TIMESTAMP(3),
    "category" "TaskCategory" NOT NULL DEFAULT 'GENERAL',
    "tags" TEXT[],
    "estimatedHours" DOUBLE PRECISION,
    "actualHours" DOUBLE PRECISION,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "userId" TEXT NOT NULL,
    "remediationPlanId" TEXT,

    CONSTRAINT "Task_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ChatSession" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL DEFAULT 'New Chat',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "userId" TEXT NOT NULL,

    CONSTRAINT "ChatSession_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ChatMessage" (
    "id" TEXT NOT NULL,
    "role" "MessageRole" NOT NULL,
    "content" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "contextType" TEXT,
    "contextId" TEXT,
    "sessionId" TEXT NOT NULL,

    CONSTRAINT "ChatMessage_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CopilotSession" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL DEFAULT 'New Chat',
    "contextType" "CopilotContextType" NOT NULL DEFAULT 'GENERAL',
    "pipelineStackId" TEXT,
    "nodeIds" TEXT[],
    "isDebugSession" BOOLEAN NOT NULL DEFAULT false,
    "debugIssueId" TEXT,
    "model" TEXT NOT NULL DEFAULT 'claude-sonnet',
    "memorySummary" TEXT,
    "totalInputTokens" INTEGER NOT NULL DEFAULT 0,
    "totalOutputTokens" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "userId" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "CopilotSession_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CopilotMessage" (
    "id" TEXT NOT NULL,
    "role" "MessageRole" NOT NULL,
    "content" TEXT NOT NULL,
    "toolCalls" JSONB,
    "toolResults" JSONB,
    "contextUsed" JSONB,
    "inputTokens" INTEGER,
    "outputTokens" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "sessionId" TEXT NOT NULL,

    CONSTRAINT "CopilotMessage_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LineageEvent" (
    "id" TEXT NOT NULL,
    "eventType" TEXT NOT NULL,
    "eventTime" TIMESTAMP(3) NOT NULL,
    "jobNamespace" TEXT NOT NULL,
    "jobName" TEXT NOT NULL,
    "runId" TEXT NOT NULL,
    "parentRunId" TEXT,
    "inputs" JSONB NOT NULL,
    "outputs" JSONB NOT NULL,
    "jobFacets" JSONB,
    "runFacets" JSONB,
    "processed" BOOLEAN NOT NULL DEFAULT false,
    "processedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "LineageEvent_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DebugSession" (
    "id" TEXT NOT NULL,
    "issueType" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT,
    "symptomNodeId" TEXT,
    "symptomDetails" JSONB,
    "rootCauseNodeId" TEXT,
    "rootCauseType" TEXT,
    "rootCauseDetails" JSONB,
    "status" "DebugStatus" NOT NULL DEFAULT 'INVESTIGATING',
    "resolution" TEXT,
    "resolvedAt" TIMESTAMP(3),
    "startedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "mttr" INTEGER,
    "investigationSteps" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "copilotSessionId" TEXT,

    CONSTRAINT "DebugSession_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Notification" (
    "id" TEXT NOT NULL,
    "type" "NotificationType" NOT NULL,
    "title" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "read" BOOLEAN NOT NULL DEFAULT false,
    "link" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "userId" TEXT NOT NULL,

    CONSTRAINT "Notification_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AuditLog" (
    "id" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "userId" TEXT,
    "userEmail" TEXT,
    "userName" TEXT,
    "resourceType" TEXT,
    "resourceId" TEXT,
    "resourceName" TEXT,
    "metadata" JSONB,
    "ipAddress" TEXT,
    "userAgent" TEXT,
    "status" TEXT NOT NULL DEFAULT 'success',
    "errorMessage" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "organizationId" TEXT,

    CONSTRAINT "AuditLog_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AppliedFix" (
    "id" TEXT NOT NULL,
    "fixType" TEXT NOT NULL,
    "fixTitle" TEXT NOT NULL,
    "fixCode" TEXT NOT NULL,
    "language" TEXT NOT NULL,
    "repoOwner" TEXT NOT NULL,
    "repoName" TEXT NOT NULL,
    "filePath" TEXT NOT NULL,
    "branchName" TEXT NOT NULL,
    "writeMode" TEXT NOT NULL,
    "commitSha" TEXT,
    "prNumber" INTEGER,
    "prUrl" TEXT,
    "prStatus" TEXT NOT NULL DEFAULT 'open',
    "reportId" TEXT,
    "findingId" TEXT,
    "findingTitle" TEXT,
    "table" TEXT,
    "column" TEXT,
    "issueType" TEXT,
    "issueCategory" TEXT,
    "severity" TEXT,
    "metricSnapshot" JSONB,
    "confidenceScore" DOUBLE PRECISION,
    "generationMethod" TEXT,
    "status" "AppliedFixStatus" NOT NULL DEFAULT 'PENDING',
    "appliedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "mergedAt" TIMESTAMP(3),
    "errorMessage" TEXT,
    "userId" TEXT NOT NULL,
    "organizationId" TEXT,

    CONSTRAINT "AppliedFix_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ChangePlan" (
    "id" TEXT NOT NULL,
    "version" INTEGER NOT NULL DEFAULT 1,
    "title" TEXT NOT NULL,
    "description" TEXT,
    "rootCause" TEXT,
    "patches" JSONB NOT NULL,
    "validations" JSONB,
    "impactAnalysis" JSONB,
    "status" "ChangePlanStatus" NOT NULL DEFAULT 'DRAFT',
    "prUrl" TEXT,
    "prNumber" INTEGER,
    "branchName" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "createdBy" TEXT,
    "sessionId" TEXT,
    "appliedFixId" TEXT,

    CONSTRAINT "ChangePlan_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FixOutcome" (
    "id" TEXT NOT NULL,
    "appliedFixId" TEXT NOT NULL,
    "outcome" "FixOutcomeStatus" NOT NULL DEFAULT 'PENDING',
    "detectionMethod" "OutcomeDetectionMethod" NOT NULL DEFAULT 'AUTOMATIC',
    "detectedAt" TIMESTAMP(3),
    "timeToResolution" INTEGER,
    "metricsBefore" JSONB,
    "metricsAfter" JSONB,
    "improvement" DOUBLE PRECISION,
    "userRating" INTEGER,
    "userFeedback" TEXT,
    "feedbackGivenAt" TIMESTAMP(3),
    "feedbackUserId" TEXT,
    "issueFingerprintId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT,

    CONSTRAINT "FixOutcome_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "IssueFingerprint" (
    "id" TEXT NOT NULL,
    "issueType" TEXT NOT NULL,
    "issueCategory" TEXT NOT NULL,
    "severity" TEXT NOT NULL,
    "tablePattern" TEXT,
    "columnPattern" TEXT,
    "warehouseType" TEXT,
    "hasDBT" BOOLEAN NOT NULL DEFAULT false,
    "hasAirflow" BOOLEAN NOT NULL DEFAULT false,
    "hasPrefect" BOOLEAN NOT NULL DEFAULT false,
    "hasFivetran" BOOLEAN NOT NULL DEFAULT false,
    "thresholdExceededBy" DOUBLE PRECISION,
    "dayOfWeek" INTEGER,
    "hourOfDay" INTEGER,
    "isWeekend" BOOLEAN,
    "isMonthEnd" BOOLEAN,
    "isQuarterEnd" BOOLEAN,
    "embedding" BYTEA,
    "embeddingModel" TEXT,
    "occurrenceCount" INTEGER NOT NULL DEFAULT 1,
    "lastSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "firstSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "organizationId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "IssueFingerprint_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FixPattern" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "issueType" TEXT NOT NULL,
    "issueCategory" TEXT NOT NULL,
    "requiredStack" JSONB,
    "requiredContext" JSONB,
    "fixType" TEXT NOT NULL,
    "fixTemplate" TEXT NOT NULL,
    "fixLanguage" TEXT NOT NULL,
    "fixFilePath" TEXT,
    "placeholders" JSONB,
    "successCount" INTEGER NOT NULL DEFAULT 0,
    "failureCount" INTEGER NOT NULL DEFAULT 0,
    "successRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "totalApplications" INTEGER NOT NULL DEFAULT 0,
    "avgTimeToResolve" INTEGER,
    "confidenceScore" DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    "isBuiltIn" BOOLEAN NOT NULL DEFAULT false,
    "isApproved" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT,

    CONSTRAINT "FixPattern_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FixPatternMatch" (
    "id" TEXT NOT NULL,
    "fingerprintId" TEXT NOT NULL,
    "patternId" TEXT NOT NULL,
    "matchScore" DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    "usageCount" INTEGER NOT NULL DEFAULT 0,
    "successCount" INTEGER NOT NULL DEFAULT 0,
    "localSuccessRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "FixPatternMatch_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Integration" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "type" "IntegrationType" NOT NULL,
    "status" "IntegrationStatus" NOT NULL DEFAULT 'INACTIVE',
    "credentials" JSONB,
    "accessToken" TEXT,
    "refreshToken" TEXT,
    "tokenExpiry" TIMESTAMP(3),
    "config" JSONB,
    "metadata" JSONB,
    "connectionInfo" TEXT,
    "lastSyncAt" TIMESTAMP(3),
    "lastTestAt" TIMESTAMP(3),
    "lastError" TEXT,
    "healthScore" INTEGER,
    "scanCount" INTEGER NOT NULL DEFAULT 0,
    "lastScanAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "Integration_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "WorkflowRun" (
    "id" TEXT NOT NULL,
    "workflowId" TEXT NOT NULL,
    "workflowName" TEXT NOT NULL,
    "status" "WorkflowStatus" NOT NULL DEFAULT 'PENDING',
    "inputData" JSONB,
    "outputData" JSONB,
    "errorMessage" TEXT,
    "startedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),
    "reportId" TEXT,
    "userId" TEXT,

    CONSTRAINT "WorkflowRun_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MetricBaseline" (
    "id" TEXT NOT NULL,
    "metricKey" TEXT NOT NULL,
    "tableName" TEXT NOT NULL,
    "columnName" TEXT,
    "metricType" "MetricType" NOT NULL,
    "mean" DOUBLE PRECISION NOT NULL,
    "stdDev" DOUBLE PRECISION NOT NULL,
    "median" DOUBLE PRECISION NOT NULL,
    "minValue" DOUBLE PRECISION,
    "maxValue" DOUBLE PRECISION,
    "percentile25" DOUBLE PRECISION,
    "percentile50" DOUBLE PRECISION,
    "percentile75" DOUBLE PRECISION,
    "percentile90" DOUBLE PRECISION,
    "percentile99" DOUBLE PRECISION,
    "hourlyPatterns" JSONB,
    "dailyPatterns" JSONB,
    "trendDirection" TEXT NOT NULL DEFAULT 'stable',
    "trendSlope" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "sampleCount" INTEGER NOT NULL DEFAULT 0,
    "windowDays" INTEGER NOT NULL DEFAULT 30,
    "lastValue" DOUBLE PRECISION,
    "lastObservedAt" TIMESTAMP(3),
    "sensitivity" DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,

    CONSTRAINT "MetricBaseline_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MetricObservation" (
    "id" TEXT NOT NULL,
    "value" DOUBLE PRECISION NOT NULL,
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "hourOfDay" INTEGER,
    "dayOfWeek" INTEGER,
    "isAnomaly" BOOLEAN NOT NULL DEFAULT false,
    "anomalyScore" DOUBLE PRECISION,
    "anomalySeverity" TEXT,
    "baselineId" TEXT NOT NULL,

    CONSTRAINT "MetricObservation_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ScanSnapshot" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "scanType" TEXT NOT NULL,
    "scanTimestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "scanDurationMs" INTEGER,
    "overallScore" INTEGER NOT NULL,
    "tablesScanned" INTEGER NOT NULL,
    "findingsCount" INTEGER NOT NULL,
    "criticalCount" INTEGER NOT NULL,
    "highCount" INTEGER NOT NULL,
    "mediumCount" INTEGER NOT NULL,
    "lowCount" INTEGER NOT NULL,
    "autoFixAvailable" INTEGER NOT NULL DEFAULT 0,
    "autoFixApplied" INTEGER NOT NULL DEFAULT 0,
    "avgFreshnessHours" DOUBLE PRECISION,
    "avgNullRate" DOUBLE PRECISION,
    "avgDuplicateRate" DOUBLE PRECISION,
    "schemaChanges" INTEGER,
    "secretsExposed" INTEGER,
    "piiTablesFound" INTEGER,
    "coveragePercent" DOUBLE PRECISION,
    "testCoverage" DOUBLE PRECISION,
    "incidentsCreated" INTEGER NOT NULL DEFAULT 0,
    "mttr" INTEGER,
    "industry" TEXT,
    "companySize" TEXT,
    "findingsJson" JSONB,
    "metricsJson" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ScanSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "OrganizationRiskProfile" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "overallRiskScore" INTEGER NOT NULL DEFAULT 50,
    "dataQualityRisk" INTEGER NOT NULL DEFAULT 50,
    "dataFreshnessRisk" INTEGER NOT NULL DEFAULT 50,
    "schemaStabilityRisk" INTEGER NOT NULL DEFAULT 50,
    "securityRisk" INTEGER NOT NULL DEFAULT 50,
    "operationalRisk" INTEGER NOT NULL DEFAULT 50,
    "riskTrend" TEXT NOT NULL DEFAULT 'stable',
    "riskTrendPercent" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "avgDrrScore" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "avgMttr" INTEGER NOT NULL DEFAULT 0,
    "avgMttd" INTEGER NOT NULL DEFAULT 0,
    "incidentFrequency" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "coveragePercent" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "totalTables" INTEGER NOT NULL DEFAULT 0,
    "monitoredTables" INTEGER NOT NULL DEFAULT 0,
    "totalScansRun" INTEGER NOT NULL DEFAULT 0,
    "scansLast30Days" INTEGER NOT NULL DEFAULT 0,
    "avgNullRate" DOUBLE PRECISION,
    "avgDuplicateRate" DOUBLE PRECISION,
    "avgFreshnessHours" DOUBLE PRECISION,
    "schemaChangeFrequency" DOUBLE PRECISION,
    "secretsExposedEver" INTEGER NOT NULL DEFAULT 0,
    "piiTablesCount" INTEGER NOT NULL DEFAULT 0,
    "encryptionCoverage" DOUBLE PRECISION,
    "industry" TEXT,
    "companySize" TEXT,
    "dataMaturityLevel" TEXT NOT NULL DEFAULT 'emerging',
    "lastCalculatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "OrganizationRiskProfile_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "IndustryBenchmark" (
    "id" TEXT NOT NULL,
    "industry" TEXT NOT NULL,
    "companySize" TEXT,
    "period" TEXT NOT NULL,
    "organizationCount" INTEGER NOT NULL DEFAULT 0,
    "scanCount" INTEGER NOT NULL DEFAULT 0,
    "drrScore_p25" DOUBLE PRECISION,
    "drrScore_p50" DOUBLE PRECISION,
    "drrScore_p75" DOUBLE PRECISION,
    "drrScore_p90" DOUBLE PRECISION,
    "avgRiskScore" DOUBLE PRECISION,
    "riskScore_p25" DOUBLE PRECISION,
    "riskScore_p50" DOUBLE PRECISION,
    "riskScore_p75" DOUBLE PRECISION,
    "avgMttr" INTEGER,
    "mttr_p25" INTEGER,
    "mttr_p50" INTEGER,
    "mttr_p75" INTEGER,
    "avgCoverage" DOUBLE PRECISION,
    "coverage_p50" DOUBLE PRECISION,
    "avgNullRate" DOUBLE PRECISION,
    "avgFreshnessHours" DOUBLE PRECISION,
    "avgIncidentRate" DOUBLE PRECISION,
    "calculatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "IndustryBenchmark_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RiskAPISubscription" (
    "id" TEXT NOT NULL,
    "partnerName" TEXT NOT NULL,
    "partnerType" TEXT NOT NULL,
    "contactEmail" TEXT NOT NULL,
    "contactName" TEXT,
    "apiKey" TEXT NOT NULL,
    "apiKeyHash" TEXT NOT NULL,
    "plan" "RiskAPIPlan" NOT NULL DEFAULT 'STANDARD',
    "status" "RiskAPIStatus" NOT NULL DEFAULT 'ACTIVE',
    "requestsPerMonth" INTEGER NOT NULL DEFAULT 1000,
    "requestsUsed" INTEGER NOT NULL DEFAULT 0,
    "requestsResetAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "monthlyFee" DOUBLE PRECISION,
    "perRequestFee" DOUBLE PRECISION,
    "allowedEndpoints" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "allowedIndustries" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "lastRequestAt" TIMESTAMP(3),
    "totalRequestsEver" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "RiskAPISubscription_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RiskAPIRequest" (
    "id" TEXT NOT NULL,
    "subscriptionId" TEXT NOT NULL,
    "endpoint" TEXT NOT NULL,
    "method" TEXT NOT NULL,
    "requestParams" JSONB,
    "responseStatus" INTEGER NOT NULL,
    "responseTimeMs" INTEGER,
    "billable" BOOLEAN NOT NULL DEFAULT true,
    "billedAmount" DOUBLE PRECISION,
    "clientIp" TEXT,
    "userAgent" TEXT,
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "RiskAPIRequest_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Finding" (
    "id" TEXT NOT NULL,
    "fingerprint" TEXT NOT NULL,
    "table" TEXT NOT NULL,
    "column" TEXT,
    "scanType" TEXT NOT NULL,
    "findingType" TEXT NOT NULL,
    "severity" "FindingSeverity" NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "details" JSONB,
    "suggestedFix" TEXT,
    "fixType" TEXT,
    "fixConfidence" DOUBLE PRECISION,
    "status" "FindingStatus" NOT NULL DEFAULT 'OPEN',
    "firstSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "resolvedAt" TIMESTAMP(3),
    "scanCount" INTEGER NOT NULL DEFAULT 1,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,
    "reportId" TEXT,
    "matchedRuleId" TEXT,

    CONSTRAINT "Finding_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FindingResponse" (
    "id" TEXT NOT NULL,
    "responseType" "ResponseType" NOT NULL,
    "reason" TEXT,
    "justification" TEXT,
    "approvedBy" TEXT,
    "approvedAt" TIMESTAMP(3),
    "expiresAt" TIMESTAMP(3),
    "verified" BOOLEAN NOT NULL DEFAULT false,
    "verifiedBy" TEXT,
    "verifiedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "findingId" TEXT NOT NULL,
    "userId" TEXT,
    "userName" TEXT,

    CONSTRAINT "FindingResponse_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FindingRule" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "conditions" JSONB NOT NULL,
    "action" "RuleAction" NOT NULL DEFAULT 'REDUCE_SEVERITY',
    "targetSeverity" "FindingSeverity",
    "suppressReason" TEXT,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "priority" INTEGER NOT NULL DEFAULT 0,
    "createdBy" TEXT,
    "approvedBy" TEXT,
    "approvedAt" TIMESTAMP(3),
    "expiresAt" TIMESTAMP(3),
    "matchCount" INTEGER NOT NULL DEFAULT 0,
    "lastMatchAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "FindingRule_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SuppressionOverride" (
    "id" TEXT NOT NULL,
    "table" TEXT NOT NULL,
    "column" TEXT,
    "findingType" TEXT,
    "suppressionSource" TEXT NOT NULL,
    "decision" "OverrideDecision" NOT NULL,
    "reason" TEXT,
    "originalClassification" JSONB,
    "createdBy" TEXT,
    "createdByName" TEXT,
    "approvedBy" TEXT,
    "approvedAt" TIMESTAMP(3),
    "expiresAt" TIMESTAMP(3),
    "appliedCount" INTEGER NOT NULL DEFAULT 0,
    "lastAppliedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,

    CONSTRAINT "SuppressionOverride_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DRRScore" (
    "id" TEXT NOT NULL,
    "totalFindings" INTEGER NOT NULL,
    "resolvedFindings" INTEGER NOT NULL,
    "acknowledgedCount" INTEGER NOT NULL,
    "falsePositives" INTEGER NOT NULL,
    "acceptedRisks" INTEGER NOT NULL,
    "suppressedCount" INTEGER NOT NULL,
    "drrScore" DOUBLE PRECISION NOT NULL,
    "criticalTotal" INTEGER NOT NULL DEFAULT 0,
    "criticalResolved" INTEGER NOT NULL DEFAULT 0,
    "highTotal" INTEGER NOT NULL DEFAULT 0,
    "highResolved" INTEGER NOT NULL DEFAULT 0,
    "mediumTotal" INTEGER NOT NULL DEFAULT 0,
    "mediumResolved" INTEGER NOT NULL DEFAULT 0,
    "lowTotal" INTEGER NOT NULL DEFAULT 0,
    "lowResolved" INTEGER NOT NULL DEFAULT 0,
    "scanType" TEXT,
    "recordedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "organizationId" TEXT NOT NULL,
    "reportId" TEXT,

    CONSTRAINT "DRRScore_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ScannerPatternRule" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "tablePattern" TEXT NOT NULL,
    "columnPattern" TEXT NOT NULL,
    "findingType" TEXT NOT NULL,
    "patternType" "PatternType" NOT NULL,
    "context" JSONB NOT NULL,
    "status" "PatternRuleStatus" NOT NULL DEFAULT 'PENDING',
    "confirmedBy" TEXT,
    "confirmedAt" TIMESTAMP(3),
    "rejectedReason" TEXT,
    "detectionConfidence" DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    "timesSeen" INTEGER NOT NULL DEFAULT 1,
    "lastSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "firstSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "priority" INTEGER NOT NULL DEFAULT 0,
    "expiresAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "ScannerPatternRule_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PatternRuleApplication" (
    "id" TEXT NOT NULL,
    "ruleId" TEXT NOT NULL,
    "scanId" TEXT NOT NULL,
    "tableName" TEXT NOT NULL,
    "columnName" TEXT,
    "action" "PatternRuleAction" NOT NULL,
    "details" JSONB,
    "appliedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PatternRuleApplication_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Artifact" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "type" "ArtifactType" NOT NULL,
    "tags" TEXT[],
    "sourceSessionId" TEXT,
    "sourceMessageId" TEXT,
    "metadata" JSONB,
    "isPinned" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "userId" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "Artifact_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Monitor" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "monitorType" "MonitorKind",
    "targetFqn" TEXT,
    "targetDatabase" TEXT,
    "targetSchema" TEXT,
    "targetTable" TEXT,
    "config" JSONB,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "schedule" TEXT,
    "lastRunAt" TIMESTAMP(3),
    "lastStatus" "MonitorRunStatus",
    "nextRunAt" TIMESTAMP(3),
    "baselineMean" DOUBLE PRECISION,
    "baselineStddev" DOUBLE PRECISION,
    "baselineCount" INTEGER,
    "baselineUpdatedAt" TIMESTAMP(3),
    "taskMode" TEXT,
    "prompt" TEXT,
    "description" TEXT,
    "alertChannels" TEXT[],
    "alertConfig" JSONB,
    "alertOnStatus" TEXT[],
    "timezone" TEXT DEFAULT 'UTC',
    "createdBy" TEXT,
    "source" TEXT,
    "externalId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "organizationId" TEXT NOT NULL,
    "integrationId" TEXT,

    CONSTRAINT "Monitor_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MonitorRun" (
    "id" TEXT NOT NULL,
    "status" "MonitorRunStatus" NOT NULL,
    "value" DOUBLE PRECISION,
    "threshold" DOUBLE PRECISION,
    "message" TEXT,
    "details" JSONB,
    "sqlExecuted" TEXT,
    "startedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),
    "durationMs" INTEGER,
    "monitorId" TEXT NOT NULL,

    CONSTRAINT "MonitorRun_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CoverageSnapshot" (
    "id" TEXT NOT NULL,
    "overallScore" DOUBLE PRECISION NOT NULL,
    "totalNodes" INTEGER NOT NULL,
    "nodesWithFullCoverage" INTEGER NOT NULL,
    "nodesWithPartialCoverage" INTEGER NOT NULL,
    "nodesWithNoCoverage" INTEGER NOT NULL,
    "freshnessScore" DOUBLE PRECISION,
    "volumeScore" DOUBLE PRECISION,
    "schemaScore" DOUBLE PRECISION,
    "qualityScore" DOUBLE PRECISION,
    "lineageScore" DOUBLE PRECISION,
    "ownershipScore" DOUBLE PRECISION,
    "documentationScore" DOUBLE PRECISION,
    "criticalGaps" INTEGER NOT NULL DEFAULT 0,
    "highGaps" INTEGER NOT NULL DEFAULT 0,
    "mediumGaps" INTEGER NOT NULL DEFAULT 0,
    "lowGaps" INTEGER NOT NULL DEFAULT 0,
    "nodeScores" JSONB,
    "gaps" JSONB,
    "recommendations" JSONB,
    "source" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "organizationId" TEXT NOT NULL,

    CONSTRAINT "CoverageSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE INDEX "User_organizationId_idx" ON "User"("organizationId");

-- CreateIndex
CREATE INDEX "Account_userId_idx" ON "Account"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "Account_provider_providerAccountId_key" ON "Account"("provider", "providerAccountId");

-- CreateIndex
CREATE UNIQUE INDEX "Session_sessionToken_key" ON "Session"("sessionToken");

-- CreateIndex
CREATE INDEX "Session_userId_idx" ON "Session"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "VerificationToken_token_key" ON "VerificationToken"("token");

-- CreateIndex
CREATE UNIQUE INDEX "VerificationToken_identifier_token_key" ON "VerificationToken"("identifier", "token");

-- CreateIndex
CREATE UNIQUE INDEX "Organization_domain_key" ON "Organization"("domain");

-- CreateIndex
CREATE INDEX "Organization_domain_idx" ON "Organization"("domain");

-- CreateIndex
CREATE INDEX "TeamMember_organizationId_idx" ON "TeamMember"("organizationId");

-- CreateIndex
CREATE INDEX "TeamMember_role_idx" ON "TeamMember"("role");

-- CreateIndex
CREATE INDEX "TeamMember_status_idx" ON "TeamMember"("status");

-- CreateIndex
CREATE UNIQUE INDEX "TeamMember_userId_organizationId_key" ON "TeamMember"("userId", "organizationId");

-- CreateIndex
CREATE UNIQUE INDEX "TeamInvite_token_key" ON "TeamInvite"("token");

-- CreateIndex
CREATE INDEX "TeamInvite_organizationId_idx" ON "TeamInvite"("organizationId");

-- CreateIndex
CREATE INDEX "TeamInvite_token_idx" ON "TeamInvite"("token");

-- CreateIndex
CREATE INDEX "TeamInvite_status_idx" ON "TeamInvite"("status");

-- CreateIndex
CREATE INDEX "TeamInvite_email_idx" ON "TeamInvite"("email");

-- CreateIndex
CREATE UNIQUE INDEX "TeamInvite_email_organizationId_key" ON "TeamInvite"("email", "organizationId");

-- CreateIndex
CREATE INDEX "PipelineStack_organizationId_idx" ON "PipelineStack"("organizationId");

-- CreateIndex
CREATE INDEX "PipelineStack_status_idx" ON "PipelineStack"("status");

-- CreateIndex
CREATE UNIQUE INDEX "PipelineContext_pipelineStackId_key" ON "PipelineContext"("pipelineStackId");

-- CreateIndex
CREATE INDEX "PipelineContext_pipelineStackId_idx" ON "PipelineContext"("pipelineStackId");

-- CreateIndex
CREATE INDEX "PipelineContext_onboardingStatus_idx" ON "PipelineContext"("onboardingStatus");

-- CreateIndex
CREATE INDEX "PipelineAccess_pipelineId_idx" ON "PipelineAccess"("pipelineId");

-- CreateIndex
CREATE INDEX "PipelineAccess_userId_idx" ON "PipelineAccess"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "PipelineAccess_userId_pipelineId_key" ON "PipelineAccess"("userId", "pipelineId");

-- CreateIndex
CREATE INDEX "PipelineNode_stackId_idx" ON "PipelineNode"("stackId");

-- CreateIndex
CREATE INDEX "PipelineNode_layer_idx" ON "PipelineNode"("layer");

-- CreateIndex
CREATE INDEX "PipelineNode_toolType_idx" ON "PipelineNode"("toolType");

-- CreateIndex
CREATE INDEX "PipelineNode_status_idx" ON "PipelineNode"("status");

-- CreateIndex
CREATE INDEX "PipelineEdge_sourceId_idx" ON "PipelineEdge"("sourceId");

-- CreateIndex
CREATE INDEX "PipelineEdge_targetId_idx" ON "PipelineEdge"("targetId");

-- CreateIndex
CREATE INDEX "PipelineEdge_stackId_idx" ON "PipelineEdge"("stackId");

-- CreateIndex
CREATE UNIQUE INDEX "PipelineEdge_sourceId_targetId_key" ON "PipelineEdge"("sourceId", "targetId");

-- CreateIndex
CREATE INDEX "PipelineScan_stackId_idx" ON "PipelineScan"("stackId");

-- CreateIndex
CREATE INDEX "PipelineScan_status_idx" ON "PipelineScan"("status");

-- CreateIndex
CREATE INDEX "PipelineScan_createdAt_idx" ON "PipelineScan"("createdAt");

-- CreateIndex
CREATE INDEX "PipelineNodeFinding_nodeId_idx" ON "PipelineNodeFinding"("nodeId");

-- CreateIndex
CREATE INDEX "PipelineNodeFinding_scanId_idx" ON "PipelineNodeFinding"("scanId");

-- CreateIndex
CREATE INDEX "PipelineNodeFinding_severity_idx" ON "PipelineNodeFinding"("severity");

-- CreateIndex
CREATE INDEX "PipelineNodeFinding_type_idx" ON "PipelineNodeFinding"("type");

-- CreateIndex
CREATE INDEX "DataContract_organizationId_idx" ON "DataContract"("organizationId");

-- CreateIndex
CREATE INDEX "DataContract_integrationId_idx" ON "DataContract"("integrationId");

-- CreateIndex
CREATE INDEX "DataContract_fullName_idx" ON "DataContract"("fullName");

-- CreateIndex
CREATE INDEX "DataContract_status_idx" ON "DataContract"("status");

-- CreateIndex
CREATE UNIQUE INDEX "DataContract_organizationId_fullName_key" ON "DataContract"("organizationId", "fullName");

-- CreateIndex
CREATE INDEX "ContractViolation_contractId_idx" ON "ContractViolation"("contractId");

-- CreateIndex
CREATE INDEX "ContractViolation_createdAt_idx" ON "ContractViolation"("createdAt");

-- CreateIndex
CREATE INDEX "TableConfig_organizationId_idx" ON "TableConfig"("organizationId");

-- CreateIndex
CREATE INDEX "TableConfig_integrationId_idx" ON "TableConfig"("integrationId");

-- CreateIndex
CREATE INDEX "TableConfig_fullName_idx" ON "TableConfig"("fullName");

-- CreateIndex
CREATE UNIQUE INDEX "TableConfig_organizationId_fullName_key" ON "TableConfig"("organizationId", "fullName");

-- CreateIndex
CREATE INDEX "LineageNode_organizationId_idx" ON "LineageNode"("organizationId");

-- CreateIndex
CREATE INDEX "LineageNode_integrationId_idx" ON "LineageNode"("integrationId");

-- CreateIndex
CREATE INDEX "LineageNode_name_idx" ON "LineageNode"("name");

-- CreateIndex
CREATE UNIQUE INDEX "LineageNode_organizationId_name_key" ON "LineageNode"("organizationId", "name");

-- CreateIndex
CREATE INDEX "LineageEdge_sourceId_idx" ON "LineageEdge"("sourceId");

-- CreateIndex
CREATE INDEX "LineageEdge_targetId_idx" ON "LineageEdge"("targetId");

-- CreateIndex
CREATE INDEX "LineageEdge_organizationId_idx" ON "LineageEdge"("organizationId");

-- CreateIndex
CREATE UNIQUE INDEX "LineageEdge_sourceId_targetId_key" ON "LineageEdge"("sourceId", "targetId");

-- CreateIndex
CREATE INDEX "LineageSnapshot_organizationId_idx" ON "LineageSnapshot"("organizationId");

-- CreateIndex
CREATE INDEX "LineageSnapshot_integrationId_idx" ON "LineageSnapshot"("integrationId");

-- CreateIndex
CREATE INDEX "Report_userId_idx" ON "Report"("userId");

-- CreateIndex
CREATE INDEX "Report_organizationId_idx" ON "Report"("organizationId");

-- CreateIndex
CREATE INDEX "Report_status_idx" ON "Report"("status");

-- CreateIndex
CREATE INDEX "Report_type_idx" ON "Report"("type");

-- CreateIndex
CREATE INDEX "ScanSchedule_organizationId_idx" ON "ScanSchedule"("organizationId");

-- CreateIndex
CREATE INDEX "ScanSchedule_enabled_idx" ON "ScanSchedule"("enabled");

-- CreateIndex
CREATE INDEX "ScanSchedule_nextRunAt_idx" ON "ScanSchedule"("nextRunAt");

-- CreateIndex
CREATE UNIQUE INDEX "RemediationPlan_reportId_key" ON "RemediationPlan"("reportId");

-- CreateIndex
CREATE INDEX "RemediationPlan_userId_idx" ON "RemediationPlan"("userId");

-- CreateIndex
CREATE INDEX "RemediationPlan_organizationId_idx" ON "RemediationPlan"("organizationId");

-- CreateIndex
CREATE INDEX "RemediationPlan_status_idx" ON "RemediationPlan"("status");

-- CreateIndex
CREATE INDEX "Task_userId_idx" ON "Task"("userId");

-- CreateIndex
CREATE INDEX "Task_remediationPlanId_idx" ON "Task"("remediationPlanId");

-- CreateIndex
CREATE INDEX "Task_status_idx" ON "Task"("status");

-- CreateIndex
CREATE INDEX "Task_dueDate_idx" ON "Task"("dueDate");

-- CreateIndex
CREATE INDEX "ChatSession_userId_idx" ON "ChatSession"("userId");

-- CreateIndex
CREATE INDEX "ChatMessage_sessionId_idx" ON "ChatMessage"("sessionId");

-- CreateIndex
CREATE INDEX "CopilotSession_userId_idx" ON "CopilotSession"("userId");

-- CreateIndex
CREATE INDEX "CopilotSession_organizationId_idx" ON "CopilotSession"("organizationId");

-- CreateIndex
CREATE INDEX "CopilotSession_contextType_idx" ON "CopilotSession"("contextType");

-- CreateIndex
CREATE INDEX "CopilotMessage_sessionId_idx" ON "CopilotMessage"("sessionId");

-- CreateIndex
CREATE INDEX "LineageEvent_organizationId_idx" ON "LineageEvent"("organizationId");

-- CreateIndex
CREATE INDEX "LineageEvent_jobNamespace_jobName_idx" ON "LineageEvent"("jobNamespace", "jobName");

-- CreateIndex
CREATE INDEX "LineageEvent_runId_idx" ON "LineageEvent"("runId");

-- CreateIndex
CREATE INDEX "LineageEvent_eventTime_idx" ON "LineageEvent"("eventTime");

-- CreateIndex
CREATE INDEX "LineageEvent_processed_idx" ON "LineageEvent"("processed");

-- CreateIndex
CREATE UNIQUE INDEX "DebugSession_copilotSessionId_key" ON "DebugSession"("copilotSessionId");

-- CreateIndex
CREATE INDEX "DebugSession_organizationId_idx" ON "DebugSession"("organizationId");

-- CreateIndex
CREATE INDEX "DebugSession_status_idx" ON "DebugSession"("status");

-- CreateIndex
CREATE INDEX "DebugSession_issueType_idx" ON "DebugSession"("issueType");

-- CreateIndex
CREATE INDEX "Notification_userId_idx" ON "Notification"("userId");

-- CreateIndex
CREATE INDEX "Notification_read_idx" ON "Notification"("read");

-- CreateIndex
CREATE INDEX "AuditLog_organizationId_idx" ON "AuditLog"("organizationId");

-- CreateIndex
CREATE INDEX "AuditLog_userId_idx" ON "AuditLog"("userId");

-- CreateIndex
CREATE INDEX "AuditLog_action_idx" ON "AuditLog"("action");

-- CreateIndex
CREATE INDEX "AuditLog_category_idx" ON "AuditLog"("category");

-- CreateIndex
CREATE INDEX "AuditLog_createdAt_idx" ON "AuditLog"("createdAt");

-- CreateIndex
CREATE INDEX "AuditLog_resourceType_resourceId_idx" ON "AuditLog"("resourceType", "resourceId");

-- CreateIndex
CREATE INDEX "AppliedFix_organizationId_idx" ON "AppliedFix"("organizationId");

-- CreateIndex
CREATE INDEX "AppliedFix_userId_idx" ON "AppliedFix"("userId");

-- CreateIndex
CREATE INDEX "AppliedFix_reportId_idx" ON "AppliedFix"("reportId");

-- CreateIndex
CREATE INDEX "AppliedFix_prStatus_idx" ON "AppliedFix"("prStatus");

-- CreateIndex
CREATE INDEX "AppliedFix_status_idx" ON "AppliedFix"("status");

-- CreateIndex
CREATE INDEX "AppliedFix_issueType_idx" ON "AppliedFix"("issueType");

-- CreateIndex
CREATE INDEX "AppliedFix_table_idx" ON "AppliedFix"("table");

-- CreateIndex
CREATE UNIQUE INDEX "ChangePlan_appliedFixId_key" ON "ChangePlan"("appliedFixId");

-- CreateIndex
CREATE INDEX "ChangePlan_status_idx" ON "ChangePlan"("status");

-- CreateIndex
CREATE INDEX "ChangePlan_sessionId_idx" ON "ChangePlan"("sessionId");

-- CreateIndex
CREATE INDEX "ChangePlan_createdAt_idx" ON "ChangePlan"("createdAt");

-- CreateIndex
CREATE UNIQUE INDEX "FixOutcome_appliedFixId_key" ON "FixOutcome"("appliedFixId");

-- CreateIndex
CREATE INDEX "FixOutcome_outcome_idx" ON "FixOutcome"("outcome");

-- CreateIndex
CREATE INDEX "FixOutcome_organizationId_idx" ON "FixOutcome"("organizationId");

-- CreateIndex
CREATE INDEX "FixOutcome_detectedAt_idx" ON "FixOutcome"("detectedAt");

-- CreateIndex
CREATE INDEX "FixOutcome_issueFingerprintId_idx" ON "FixOutcome"("issueFingerprintId");

-- CreateIndex
CREATE INDEX "IssueFingerprint_issueType_idx" ON "IssueFingerprint"("issueType");

-- CreateIndex
CREATE INDEX "IssueFingerprint_issueCategory_idx" ON "IssueFingerprint"("issueCategory");

-- CreateIndex
CREATE INDEX "IssueFingerprint_organizationId_idx" ON "IssueFingerprint"("organizationId");

-- CreateIndex
CREATE INDEX "IssueFingerprint_warehouseType_idx" ON "IssueFingerprint"("warehouseType");

-- CreateIndex
CREATE UNIQUE INDEX "IssueFingerprint_organizationId_issueType_tablePattern_colu_key" ON "IssueFingerprint"("organizationId", "issueType", "tablePattern", "columnPattern", "warehouseType");

-- CreateIndex
CREATE INDEX "FixPattern_issueType_idx" ON "FixPattern"("issueType");

-- CreateIndex
CREATE INDEX "FixPattern_successRate_idx" ON "FixPattern"("successRate");

-- CreateIndex
CREATE INDEX "FixPattern_organizationId_idx" ON "FixPattern"("organizationId");

-- CreateIndex
CREATE INDEX "FixPatternMatch_patternId_idx" ON "FixPatternMatch"("patternId");

-- CreateIndex
CREATE INDEX "FixPatternMatch_fingerprintId_idx" ON "FixPatternMatch"("fingerprintId");

-- CreateIndex
CREATE UNIQUE INDEX "FixPatternMatch_fingerprintId_patternId_key" ON "FixPatternMatch"("fingerprintId", "patternId");

-- CreateIndex
CREATE INDEX "Integration_organizationId_idx" ON "Integration"("organizationId");

-- CreateIndex
CREATE INDEX "Integration_type_idx" ON "Integration"("type");

-- CreateIndex
CREATE INDEX "Integration_status_idx" ON "Integration"("status");

-- CreateIndex
CREATE UNIQUE INDEX "Integration_organizationId_type_name_key" ON "Integration"("organizationId", "type", "name");

-- CreateIndex
CREATE INDEX "WorkflowRun_workflowId_idx" ON "WorkflowRun"("workflowId");

-- CreateIndex
CREATE INDEX "WorkflowRun_status_idx" ON "WorkflowRun"("status");

-- CreateIndex
CREATE INDEX "WorkflowRun_userId_idx" ON "WorkflowRun"("userId");

-- CreateIndex
CREATE INDEX "MetricBaseline_organizationId_idx" ON "MetricBaseline"("organizationId");

-- CreateIndex
CREATE INDEX "MetricBaseline_integrationId_idx" ON "MetricBaseline"("integrationId");

-- CreateIndex
CREATE INDEX "MetricBaseline_tableName_idx" ON "MetricBaseline"("tableName");

-- CreateIndex
CREATE INDEX "MetricBaseline_metricType_idx" ON "MetricBaseline"("metricType");

-- CreateIndex
CREATE UNIQUE INDEX "MetricBaseline_organizationId_metricKey_key" ON "MetricBaseline"("organizationId", "metricKey");

-- CreateIndex
CREATE INDEX "MetricObservation_baselineId_idx" ON "MetricObservation"("baselineId");

-- CreateIndex
CREATE INDEX "MetricObservation_timestamp_idx" ON "MetricObservation"("timestamp");

-- CreateIndex
CREATE INDEX "ScanSnapshot_organizationId_idx" ON "ScanSnapshot"("organizationId");

-- CreateIndex
CREATE INDEX "ScanSnapshot_scanType_idx" ON "ScanSnapshot"("scanType");

-- CreateIndex
CREATE INDEX "ScanSnapshot_scanTimestamp_idx" ON "ScanSnapshot"("scanTimestamp");

-- CreateIndex
CREATE INDEX "ScanSnapshot_industry_idx" ON "ScanSnapshot"("industry");

-- CreateIndex
CREATE UNIQUE INDEX "OrganizationRiskProfile_organizationId_key" ON "OrganizationRiskProfile"("organizationId");

-- CreateIndex
CREATE INDEX "OrganizationRiskProfile_industry_idx" ON "OrganizationRiskProfile"("industry");

-- CreateIndex
CREATE INDEX "OrganizationRiskProfile_overallRiskScore_idx" ON "OrganizationRiskProfile"("overallRiskScore");

-- CreateIndex
CREATE INDEX "OrganizationRiskProfile_dataMaturityLevel_idx" ON "OrganizationRiskProfile"("dataMaturityLevel");

-- CreateIndex
CREATE INDEX "IndustryBenchmark_industry_idx" ON "IndustryBenchmark"("industry");

-- CreateIndex
CREATE INDEX "IndustryBenchmark_period_idx" ON "IndustryBenchmark"("period");

-- CreateIndex
CREATE UNIQUE INDEX "IndustryBenchmark_industry_companySize_period_key" ON "IndustryBenchmark"("industry", "companySize", "period");

-- CreateIndex
CREATE UNIQUE INDEX "RiskAPISubscription_apiKey_key" ON "RiskAPISubscription"("apiKey");

-- CreateIndex
CREATE INDEX "RiskAPISubscription_apiKey_idx" ON "RiskAPISubscription"("apiKey");

-- CreateIndex
CREATE INDEX "RiskAPISubscription_partnerType_idx" ON "RiskAPISubscription"("partnerType");

-- CreateIndex
CREATE INDEX "RiskAPIRequest_subscriptionId_idx" ON "RiskAPIRequest"("subscriptionId");

-- CreateIndex
CREATE INDEX "RiskAPIRequest_timestamp_idx" ON "RiskAPIRequest"("timestamp");

-- CreateIndex
CREATE INDEX "RiskAPIRequest_endpoint_idx" ON "RiskAPIRequest"("endpoint");

-- CreateIndex
CREATE INDEX "Finding_organizationId_idx" ON "Finding"("organizationId");

-- CreateIndex
CREATE INDEX "Finding_integrationId_idx" ON "Finding"("integrationId");

-- CreateIndex
CREATE INDEX "Finding_status_idx" ON "Finding"("status");

-- CreateIndex
CREATE INDEX "Finding_severity_idx" ON "Finding"("severity");

-- CreateIndex
CREATE INDEX "Finding_scanType_idx" ON "Finding"("scanType");

-- CreateIndex
CREATE INDEX "Finding_fingerprint_idx" ON "Finding"("fingerprint");

-- CreateIndex
CREATE UNIQUE INDEX "Finding_organizationId_fingerprint_key" ON "Finding"("organizationId", "fingerprint");

-- CreateIndex
CREATE INDEX "FindingResponse_findingId_idx" ON "FindingResponse"("findingId");

-- CreateIndex
CREATE INDEX "FindingResponse_responseType_idx" ON "FindingResponse"("responseType");

-- CreateIndex
CREATE INDEX "FindingResponse_createdAt_idx" ON "FindingResponse"("createdAt");

-- CreateIndex
CREATE INDEX "FindingRule_organizationId_idx" ON "FindingRule"("organizationId");

-- CreateIndex
CREATE INDEX "FindingRule_isActive_idx" ON "FindingRule"("isActive");

-- CreateIndex
CREATE INDEX "SuppressionOverride_organizationId_idx" ON "SuppressionOverride"("organizationId");

-- CreateIndex
CREATE INDEX "SuppressionOverride_table_idx" ON "SuppressionOverride"("table");

-- CreateIndex
CREATE INDEX "SuppressionOverride_integrationId_idx" ON "SuppressionOverride"("integrationId");

-- CreateIndex
CREATE UNIQUE INDEX "SuppressionOverride_organizationId_table_column_findingType_key" ON "SuppressionOverride"("organizationId", "table", "column", "findingType", "suppressionSource");

-- CreateIndex
CREATE INDEX "DRRScore_organizationId_idx" ON "DRRScore"("organizationId");

-- CreateIndex
CREATE INDEX "DRRScore_recordedAt_idx" ON "DRRScore"("recordedAt");

-- CreateIndex
CREATE INDEX "DRRScore_scanType_idx" ON "DRRScore"("scanType");

-- CreateIndex
CREATE INDEX "ScannerPatternRule_organizationId_idx" ON "ScannerPatternRule"("organizationId");

-- CreateIndex
CREATE INDEX "ScannerPatternRule_status_idx" ON "ScannerPatternRule"("status");

-- CreateIndex
CREATE INDEX "ScannerPatternRule_patternType_idx" ON "ScannerPatternRule"("patternType");

-- CreateIndex
CREATE INDEX "ScannerPatternRule_isActive_idx" ON "ScannerPatternRule"("isActive");

-- CreateIndex
CREATE UNIQUE INDEX "ScannerPatternRule_organizationId_tablePattern_columnPatter_key" ON "ScannerPatternRule"("organizationId", "tablePattern", "columnPattern", "findingType", "patternType");

-- CreateIndex
CREATE INDEX "PatternRuleApplication_ruleId_idx" ON "PatternRuleApplication"("ruleId");

-- CreateIndex
CREATE INDEX "PatternRuleApplication_scanId_idx" ON "PatternRuleApplication"("scanId");

-- CreateIndex
CREATE INDEX "PatternRuleApplication_appliedAt_idx" ON "PatternRuleApplication"("appliedAt");

-- CreateIndex
CREATE INDEX "Artifact_userId_idx" ON "Artifact"("userId");

-- CreateIndex
CREATE INDEX "Artifact_organizationId_idx" ON "Artifact"("organizationId");

-- CreateIndex
CREATE INDEX "Artifact_type_idx" ON "Artifact"("type");

-- CreateIndex
CREATE INDEX "Monitor_organizationId_idx" ON "Monitor"("organizationId");

-- CreateIndex
CREATE INDEX "Monitor_targetFqn_idx" ON "Monitor"("targetFqn");

-- CreateIndex
CREATE INDEX "Monitor_monitorType_idx" ON "Monitor"("monitorType");

-- CreateIndex
CREATE INDEX "Monitor_enabled_idx" ON "Monitor"("enabled");

-- CreateIndex
CREATE UNIQUE INDEX "Monitor_organizationId_targetFqn_monitorType_key" ON "Monitor"("organizationId", "targetFqn", "monitorType");

-- CreateIndex
CREATE INDEX "MonitorRun_monitorId_idx" ON "MonitorRun"("monitorId");

-- CreateIndex
CREATE INDEX "MonitorRun_startedAt_idx" ON "MonitorRun"("startedAt");

-- CreateIndex
CREATE INDEX "MonitorRun_status_idx" ON "MonitorRun"("status");

-- CreateIndex
CREATE INDEX "CoverageSnapshot_organizationId_idx" ON "CoverageSnapshot"("organizationId");

-- CreateIndex
CREATE INDEX "CoverageSnapshot_createdAt_idx" ON "CoverageSnapshot"("createdAt");

-- AddForeignKey
ALTER TABLE "User" ADD CONSTRAINT "User_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Account" ADD CONSTRAINT "Account_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Session" ADD CONSTRAINT "Session_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TeamMember" ADD CONSTRAINT "TeamMember_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TeamMember" ADD CONSTRAINT "TeamMember_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TeamInvite" ADD CONSTRAINT "TeamInvite_invitedById_fkey" FOREIGN KEY ("invitedById") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TeamInvite" ADD CONSTRAINT "TeamInvite_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineStack" ADD CONSTRAINT "PipelineStack_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineContext" ADD CONSTRAINT "PipelineContext_pipelineStackId_fkey" FOREIGN KEY ("pipelineStackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineAccess" ADD CONSTRAINT "PipelineAccess_pipelineId_fkey" FOREIGN KEY ("pipelineId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineNode" ADD CONSTRAINT "PipelineNode_stackId_fkey" FOREIGN KEY ("stackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineNode" ADD CONSTRAINT "PipelineNode_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineEdge" ADD CONSTRAINT "PipelineEdge_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "PipelineNode"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineEdge" ADD CONSTRAINT "PipelineEdge_targetId_fkey" FOREIGN KEY ("targetId") REFERENCES "PipelineNode"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineEdge" ADD CONSTRAINT "PipelineEdge_stackId_fkey" FOREIGN KEY ("stackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineScan" ADD CONSTRAINT "PipelineScan_stackId_fkey" FOREIGN KEY ("stackId") REFERENCES "PipelineStack"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineNodeFinding" ADD CONSTRAINT "PipelineNodeFinding_nodeId_fkey" FOREIGN KEY ("nodeId") REFERENCES "PipelineNode"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PipelineNodeFinding" ADD CONSTRAINT "PipelineNodeFinding_scanId_fkey" FOREIGN KEY ("scanId") REFERENCES "PipelineScan"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DataContract" ADD CONSTRAINT "DataContract_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DataContract" ADD CONSTRAINT "DataContract_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ContractViolation" ADD CONSTRAINT "ContractViolation_contractId_fkey" FOREIGN KEY ("contractId") REFERENCES "DataContract"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TableConfig" ADD CONSTRAINT "TableConfig_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TableConfig" ADD CONSTRAINT "TableConfig_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LineageNode" ADD CONSTRAINT "LineageNode_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LineageNode" ADD CONSTRAINT "LineageNode_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LineageEdge" ADD CONSTRAINT "LineageEdge_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "LineageNode"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LineageEdge" ADD CONSTRAINT "LineageEdge_targetId_fkey" FOREIGN KEY ("targetId") REFERENCES "LineageNode"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LineageEdge" ADD CONSTRAINT "LineageEdge_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LineageSnapshot" ADD CONSTRAINT "LineageSnapshot_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LineageSnapshot" ADD CONSTRAINT "LineageSnapshot_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Report" ADD CONSTRAINT "Report_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Report" ADD CONSTRAINT "Report_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ScanSchedule" ADD CONSTRAINT "ScanSchedule_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ScanSchedule" ADD CONSTRAINT "ScanSchedule_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ScanSchedule" ADD CONSTRAINT "ScanSchedule_createdById_fkey" FOREIGN KEY ("createdById") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RemediationPlan" ADD CONSTRAINT "RemediationPlan_reportId_fkey" FOREIGN KEY ("reportId") REFERENCES "Report"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RemediationPlan" ADD CONSTRAINT "RemediationPlan_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RemediationPlan" ADD CONSTRAINT "RemediationPlan_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Task" ADD CONSTRAINT "Task_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Task" ADD CONSTRAINT "Task_remediationPlanId_fkey" FOREIGN KEY ("remediationPlanId") REFERENCES "RemediationPlan"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ChatSession" ADD CONSTRAINT "ChatSession_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ChatMessage" ADD CONSTRAINT "ChatMessage_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "ChatSession"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CopilotSession" ADD CONSTRAINT "CopilotSession_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CopilotSession" ADD CONSTRAINT "CopilotSession_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CopilotMessage" ADD CONSTRAINT "CopilotMessage_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "CopilotSession"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LineageEvent" ADD CONSTRAINT "LineageEvent_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DebugSession" ADD CONSTRAINT "DebugSession_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DebugSession" ADD CONSTRAINT "DebugSession_copilotSessionId_fkey" FOREIGN KEY ("copilotSessionId") REFERENCES "CopilotSession"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Notification" ADD CONSTRAINT "Notification_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AuditLog" ADD CONSTRAINT "AuditLog_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AuditLog" ADD CONSTRAINT "AuditLog_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AppliedFix" ADD CONSTRAINT "AppliedFix_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AppliedFix" ADD CONSTRAINT "AppliedFix_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ChangePlan" ADD CONSTRAINT "ChangePlan_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "CopilotSession"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ChangePlan" ADD CONSTRAINT "ChangePlan_appliedFixId_fkey" FOREIGN KEY ("appliedFixId") REFERENCES "AppliedFix"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FixOutcome" ADD CONSTRAINT "FixOutcome_appliedFixId_fkey" FOREIGN KEY ("appliedFixId") REFERENCES "AppliedFix"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FixOutcome" ADD CONSTRAINT "FixOutcome_issueFingerprintId_fkey" FOREIGN KEY ("issueFingerprintId") REFERENCES "IssueFingerprint"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FixOutcome" ADD CONSTRAINT "FixOutcome_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "IssueFingerprint" ADD CONSTRAINT "IssueFingerprint_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FixPattern" ADD CONSTRAINT "FixPattern_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FixPatternMatch" ADD CONSTRAINT "FixPatternMatch_fingerprintId_fkey" FOREIGN KEY ("fingerprintId") REFERENCES "IssueFingerprint"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FixPatternMatch" ADD CONSTRAINT "FixPatternMatch_patternId_fkey" FOREIGN KEY ("patternId") REFERENCES "FixPattern"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Integration" ADD CONSTRAINT "Integration_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MetricBaseline" ADD CONSTRAINT "MetricBaseline_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MetricBaseline" ADD CONSTRAINT "MetricBaseline_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MetricObservation" ADD CONSTRAINT "MetricObservation_baselineId_fkey" FOREIGN KEY ("baselineId") REFERENCES "MetricBaseline"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ScanSnapshot" ADD CONSTRAINT "ScanSnapshot_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "OrganizationRiskProfile" ADD CONSTRAINT "OrganizationRiskProfile_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RiskAPIRequest" ADD CONSTRAINT "RiskAPIRequest_subscriptionId_fkey" FOREIGN KEY ("subscriptionId") REFERENCES "RiskAPISubscription"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Finding" ADD CONSTRAINT "Finding_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Finding" ADD CONSTRAINT "Finding_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Finding" ADD CONSTRAINT "Finding_reportId_fkey" FOREIGN KEY ("reportId") REFERENCES "Report"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Finding" ADD CONSTRAINT "Finding_matchedRuleId_fkey" FOREIGN KEY ("matchedRuleId") REFERENCES "FindingRule"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FindingResponse" ADD CONSTRAINT "FindingResponse_findingId_fkey" FOREIGN KEY ("findingId") REFERENCES "Finding"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FindingRule" ADD CONSTRAINT "FindingRule_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SuppressionOverride" ADD CONSTRAINT "SuppressionOverride_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SuppressionOverride" ADD CONSTRAINT "SuppressionOverride_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DRRScore" ADD CONSTRAINT "DRRScore_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DRRScore" ADD CONSTRAINT "DRRScore_reportId_fkey" FOREIGN KEY ("reportId") REFERENCES "Report"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ScannerPatternRule" ADD CONSTRAINT "ScannerPatternRule_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PatternRuleApplication" ADD CONSTRAINT "PatternRuleApplication_ruleId_fkey" FOREIGN KEY ("ruleId") REFERENCES "ScannerPatternRule"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Artifact" ADD CONSTRAINT "Artifact_sourceSessionId_fkey" FOREIGN KEY ("sourceSessionId") REFERENCES "CopilotSession"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Artifact" ADD CONSTRAINT "Artifact_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Artifact" ADD CONSTRAINT "Artifact_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Monitor" ADD CONSTRAINT "Monitor_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Monitor" ADD CONSTRAINT "Monitor_integrationId_fkey" FOREIGN KEY ("integrationId") REFERENCES "Integration"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MonitorRun" ADD CONSTRAINT "MonitorRun_monitorId_fkey" FOREIGN KEY ("monitorId") REFERENCES "Monitor"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CoverageSnapshot" ADD CONSTRAINT "CoverageSnapshot_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;
