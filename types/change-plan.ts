/**
 * Change Plan Types
 *
 * TypeScript definitions for the change_plan feature.
 * These match the backend models in scanner/copilot/change_plan/models.py
 */

// Validation levels supported by the system
export type ValidationLevel = 'static' | 'ci' | 'sandbox';

// Status of a validation run
export type ValidationStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';

// Types of file patches
export type PatchType = 'sql_model' | 'yaml_config' | 'python_script' | 'orchestration';

// Overall status of a change plan
export type ChangePlanStatus =
  | 'draft'
  | 'validating'
  | 'validated'
  | 'applying'
  | 'applied'
  | 'failed'
  | 'rejected';

// A single file patch within a change plan
export interface FilePatch {
  file_path: string;
  patch_type: PatchType;
  new_content: string;
  rationale: string;
  original_content?: string;
  rollback_steps: string[];
  diff?: string; // Unified diff format, computed by backend
}

// Result of a validation run
export interface ValidationResult {
  level: ValidationLevel;
  status: ValidationStatus;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  errors: string[];
  warnings: string[];
  details: Record<string, unknown>;
}

// Impact analysis for a change plan
export interface ImpactAnalysis {
  affected_tables: string[];
  downstream_dependencies: string[];
  stakeholders?: string[];
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  expected_data_changes: string;
}

// A complete change plan
export interface ChangePlan {
  id: string;
  version?: number;
  title: string;
  description: string;
  root_cause: string;
  patches: FilePatch[];
  validations: Partial<Record<ValidationLevel, ValidationResult>>;
  impact_analysis?: ImpactAnalysis;
  status: ChangePlanStatus;
  created_at?: string;
  updated_at?: string;
  created_by?: string;
  session_id?: string;
  pr_url?: string;
  pr_number?: number;
}

// Tool result types for change_plan tools

export interface CreateChangePlanResult {
  success: boolean;
  plan_id?: string;
  title?: string;
  status?: ChangePlanStatus;
  patches_count?: number;
  plan?: ChangePlan;
  error?: string;
}

export interface ValidateChangePlanResult {
  success: boolean;
  plan_id?: string;
  level?: ValidationLevel;
  status?: ValidationStatus;
  errors?: string[];
  warnings?: string[];
  details?: Record<string, unknown>;
  is_validated?: boolean;
  error?: string;
}

export interface GetChangePlanResult {
  success: boolean;
  plan?: ChangePlan;
  error?: string;
}

export interface ApplyChangePlanResult {
  success: boolean;
  pr_url?: string;
  pr_number?: number;
  branch?: string;
  files_changed?: number;
  error?: string;
}

export interface ListChangePlansResult {
  success: boolean;
  count?: number;
  plans?: Array<{
    id: string;
    title: string;
    status: ChangePlanStatus;
    patches_count: number;
    validations: Record<string, ValidationStatus>;
    is_validated: boolean;
    created_at: string;
    pr_url?: string;
  }>;
  error?: string;
}

// Union type for any change plan tool result
export type ChangePlanToolResult =
  | CreateChangePlanResult
  | ValidateChangePlanResult
  | GetChangePlanResult
  | ApplyChangePlanResult
  | ListChangePlansResult;
