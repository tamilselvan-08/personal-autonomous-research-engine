// Types mirror the backend Pydantic schemas (apps/api/app/schemas).

export const TASK_STATUSES = [
  "draft",
  "planning",
  "awaiting_approval",
  "approved",
  "queued",
  "running",
  "paused",
  "completed",
  "failed",
  "cancelled",
] as const;

export type TaskStatus = (typeof TASK_STATUSES)[number];

export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export interface LoginResponse {
  user: User;
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  task_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
}

export interface ResearchTask {
  id: string;
  title: string;
  objective: string;
  description: string | null;
  status: TaskStatus;
  project_id: string | null;
  project: ProjectSummary | null;
  status_changed_at: string;
  created_at: string;
  updated_at: string;
  is_editable: boolean;
  is_deletable: boolean;
}

export interface TaskStats {
  total: number;
  by_status: Record<TaskStatus, number>;
  active: number;
  completed: number;
  failed: number;
}

export interface Activity {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

export type TaskSort = "updated_desc" | "created_desc" | "created_asc" | "title_asc";

export interface TaskInput {
  title: string;
  objective: string;
  description: string | null;
  project_id: string | null;
}

export interface ProjectInput {
  name: string;
  description: string | null;
}

export interface CheckResult {
  status: "ok" | "error";
  latency_ms: number | null;
  detail: string | null;
}

export interface Readiness {
  status: "ok" | "degraded";
  checks: Record<string, CheckResult>;
}

export interface AppSettings {
  app_name: string;
  version: string;
  environment: string;
  registration_enabled: boolean;
  api_base_url: string;
  server_time: string;
  default_timezone: string;
  python_version: string;
  database: {
    status: "ok" | "error";
    version: string | null;
    latency_ms: number | null;
    migration_revision: string | null;
  };
  features: {
    ai_providers: boolean;
    research_planning: boolean;
    research_execution: boolean;
    browser_manager: boolean;
    scheduling: boolean;
  };
}

export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: { fields?: FieldError[] } & Record<string, unknown>;
    request_id: string | null;
  };
}
