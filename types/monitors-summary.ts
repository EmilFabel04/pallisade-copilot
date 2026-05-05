// Shapes returned by the Summary tab's new aggregate endpoints.

export interface MonitorHealthSummary {
  total: number;
  healthy: number;
  warning: number;
  failing: number;
  dataAssets: number;
  pipelineTools: number;
  lastRunAt: string | null; // ISO 8601
}

export type PipelineToolStatusValue =
  | 'PASS'
  | 'WARN'
  | 'FAIL'
  | 'ERROR'
  | 'NEVER_RUN';

export interface PipelineToolStatus {
  toolType: string;       // e.g. "fivetran", "airflow", "dbt_cloud"
  displayName: string;    // e.g. "Fivetran", "Airflow", "dbt cloud"
  status: PipelineToolStatusValue;
  failCount: number;
  warnCount: number;
  monitorCount: number;
  lastRunAt: string | null;
}

export interface PipelineToolStatusResponse {
  tools: PipelineToolStatus[];
}
