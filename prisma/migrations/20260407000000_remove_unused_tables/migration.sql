-- Remove unused tables and their dependent objects
-- These tables have zero application code references

-- Drop tables with foreign key dependencies first (children before parents)

-- Fix Pattern system (learning loop)
DROP TABLE IF EXISTS "FixPatternMatch" CASCADE;
DROP TABLE IF EXISTS "FixPattern" CASCADE;
DROP TABLE IF EXISTS "FixOutcome" CASCADE;
DROP TABLE IF EXISTS "IssueFingerprint" CASCADE;

-- Finding response system (unused parts)
DROP TABLE IF EXISTS "FindingResponse" CASCADE;
DROP TABLE IF EXISTS "FindingRule" CASCADE;
DROP TABLE IF EXISTS "SuppressionOverride" CASCADE;
DROP TABLE IF EXISTS "DRRScore" CASCADE;

-- Scanner pattern rules
DROP TABLE IF EXISTS "PatternRuleApplication" CASCADE;
DROP TABLE IF EXISTS "ScannerPatternRule" CASCADE;

-- Risk Intelligence & Insurance API
DROP TABLE IF EXISTS "RiskAPIRequest" CASCADE;
DROP TABLE IF EXISTS "RiskAPISubscription" CASCADE;
DROP TABLE IF EXISTS "IndustryBenchmark" CASCADE;
DROP TABLE IF EXISTS "OrganizationRiskProfile" CASCADE;
DROP TABLE IF EXISTS "ScanSnapshot" CASCADE;

-- ML Metric baselines (replaced by MonitorBaseline)
DROP TABLE IF EXISTS "MetricObservation" CASCADE;
DROP TABLE IF EXISTS "MetricBaseline" CASCADE;

-- Coverage snapshots
DROP TABLE IF EXISTS "CoverageSnapshot" CASCADE;

-- Workflow tracking
DROP TABLE IF EXISTS "WorkflowRun" CASCADE;

-- Legacy chat (replaced by CopilotSession/CopilotMessage)
DROP TABLE IF EXISTS "ChatMessage" CASCADE;
DROP TABLE IF EXISTS "ChatSession" CASCADE;

-- Debug sessions
DROP TABLE IF EXISTS "DebugSession" CASCADE;

-- OpenLineage event storage (never implemented)
DROP TABLE IF EXISTS "LineageEvent" CASCADE;

-- Contract violations & legacy table config
DROP TABLE IF EXISTS "ContractViolation" CASCADE;
DROP TABLE IF EXISTS "TableConfig" CASCADE;

-- Remediation plans & tasks
DROP TABLE IF EXISTS "Task" CASCADE;
DROP TABLE IF EXISTS "RemediationPlan" CASCADE;

-- Drop orphaned enum types
DROP TYPE IF EXISTS "RemediationStatus";
DROP TYPE IF EXISTS "TaskStatus";
DROP TYPE IF EXISTS "TaskCategory";
DROP TYPE IF EXISTS "DebugStatus";
DROP TYPE IF EXISTS "FixOutcomeStatus";
DROP TYPE IF EXISTS "OutcomeDetectionMethod";
DROP TYPE IF EXISTS "WorkflowStatus";
DROP TYPE IF EXISTS "RiskAPIPlan";
DROP TYPE IF EXISTS "RiskAPIStatus";
DROP TYPE IF EXISTS "OverrideDecision";
DROP TYPE IF EXISTS "ResponseType";
DROP TYPE IF EXISTS "RuleAction";
DROP TYPE IF EXISTS "PatternType";
DROP TYPE IF EXISTS "PatternRuleStatus";
DROP TYPE IF EXISTS "PatternRuleAction";
DROP TYPE IF EXISTS "MetricType";

-- Remove foreign key columns that referenced dropped tables
ALTER TABLE "Finding" DROP COLUMN IF EXISTS "matchedRuleId";
