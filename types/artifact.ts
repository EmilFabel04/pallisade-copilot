/**
 * Per-kind ArtifactPayload shapes. The DB stores `payload` as JSON; this
 * union is the contract callers should use on read/write. Validated in
 * Pydantic on the scanner side (see scanner/copilot/artifacts/models.py).
 */

export type MonitorKindLiteral =
  | 'FRESHNESS'
  | 'VOLUME'
  | 'ANOMALY'
  | 'SCHEMA'
  | 'CUSTOM_SQL';

export type ValidationLevel = 'static' | 'ci' | 'sandbox';
export type ValidationStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';

export type ArtifactPayload =
  | {
      kind: 'PR_CHANGE';
      changePlanId: string;
      filesChanged: number;
      diffSummary: string;
      validationResults: Partial<Record<ValidationLevel, ValidationStatus>>;
    }
  | {
      kind: 'WAREHOUSE_QUERY';
      sql: string;
      rowCount?: number;
      executionMs?: number;
      resultPreview?: unknown[];
      error?: string;
    }
  | {
      kind: 'SCHEMA_CHANGE';
      ddl: string;
      affectedTables: string[];
      reversible: boolean;
    }
  | {
      kind: 'DBT_CORE_CHANGE';
      modelsTouched: string[];
      testsAdded: string[];
      changePlanId?: string;
    }
  | {
      kind: 'DBT_CLOUD_CHANGE';
      projectId: string;
      jobId?: string;
      environmentId?: string;
      operation: 'job_edit' | 'env_update' | 'deploy' | 'run_trigger';
    }
  | {
      kind: 'DAG';
      dagId: string;
      operation: 'create' | 'edit' | 'pause' | 'resume' | 'trigger' | 'clear';
      affectedTasks: string[];
    }
  | {
      kind: 'INGESTION_CONNECTOR';
      connectorId: string;
      operation: 'create' | 'edit' | 'pause' | 'resume' | 'trigger_sync';
      configDiff?: Record<string, unknown>;
    }
  | {
      kind: 'MONITOR';
      monitorId: string;
      monitorKind: MonitorKindLiteral;
      targetFqn?: string;
      configDiff?: Record<string, unknown>;
    }
  | {
      kind: 'WATCH';
      watchId: string;
      configDiff?: Record<string, unknown>;
    }
  | {
      kind: 'INCIDENT';
      incidentId: string;
      severity: string;
      affectedAssets: string[];
    }
  | {
      kind: 'TICKET';
      ticketKey: string;
      ticketUrl: string;
      title: string;
    }
  | {
      kind: 'NOTIFICATION_RULE';
      ruleId: string;
      channel: string;
      trigger: string;
    }
  | {
      kind: 'BI_ASSET';
      assetId: string;
      operation: 'create' | 'edit' | 'refresh';
      assetType: 'dashboard' | 'model' | 'dataset';
    }
  | {
      kind: 'STORAGE_OBJECT';
      bucket: string;
      key: string;
      operation: 'write' | 'delete' | 'copy';
    }
  | {
      kind: 'SERVER_ACTION';
      serverId: string;
      action: string;
      commandPreview?: string;
    }
  | {
      kind: 'DOCUMENT';
      format: 'md' | 'html' | 'pdf';
      body: string;
    };

export type ArtifactPayloadByKind<K extends ArtifactPayload['kind']> = Extract<
  ArtifactPayload,
  { kind: K }
>;
