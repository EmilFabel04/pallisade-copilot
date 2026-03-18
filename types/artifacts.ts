// types/artifacts.ts

export type ArtifactStatus = "proposed" | "confirmed" | "executing" | "completed" | "failed" | "cancelled";
export type ConfirmationTier = "none" | "inline" | "modal";
export type ArtifactType = "monitor_card" | "watch_preview" | "plan_preview" | "node_edit" | "policy_assignment" | "alert_config";
export type ArtifactAction = "create" | "update" | "delete";

export interface UIArtifact {
  artifact_id: string;
  type: ArtifactType;
  action: ArtifactAction;
  status: ArtifactStatus;
  data: Record<string, any>;
  confirmation_tier: ConfirmationTier;
  editable_fields: string[];
  tool_name: string;
}

export interface ActionStep {
  step_id: string;
  artifact: UIArtifact;
  order: number;
}

export interface ActionPlan {
  plan_id: string;
  description: string;
  steps: ActionStep[];
  requires_approval: boolean;
}

export interface Checkpoint {
  completed: string[];
  pending: string[];
  failed: string | null;
  error: { step_id: string; message: string; recoverable: boolean } | null;
  summary: string;
}
