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

// --- AI providers (apps/api/app/schemas/ai.py) ----------------------------------------

export const PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "gemini",
  "xai",
  "deepseek",
  "mistral",
  "openai_compatible",
] as const;
export type ProviderType = (typeof PROVIDER_TYPES)[number];

export const MODEL_ROLES = [
  "default",
  "planner",
  "researcher",
  "extractor",
  "verifier",
  "summarizer",
] as const;
export type ModelRole = (typeof MODEL_ROLES)[number];

export const MODEL_CAPABILITIES = ["json", "vision", "tools", "reasoning"] as const;
export type ModelCapability = (typeof MODEL_CAPABILITIES)[number];

export type ConnectionStatus = "connected" | "failing" | "not_tested" | "disabled";

export type HealthState =
  | "unknown"
  | "healthy"
  | "degraded"
  | "down"
  | "invalid_credentials"
  | "quota_exhausted"
  | "misconfigured";

export interface ProviderTypeInfo {
  type: ProviderType;
  label: string;
  protocol: string;
  default_base_url: string | null;
  requires_base_url: boolean;
  api_key_required: boolean;
  allow_http: boolean;
  key_hint: string;
  docs_url: string | null;
  model_examples: string[];
  verification: "mocked" | "live";
}

export interface ProviderTypes {
  encryption_configured: boolean;
  types: ProviderTypeInfo[];
}

export interface AIModel {
  id: string;
  provider_id: string;
  model_identifier: string;
  display_name: string | null;
  context_window: number | null;
  input_price_per_mtok: string | null;
  output_price_per_mtok: string | null;
  supports_json: boolean;
  capabilities: ModelCapability[];
  enabled: boolean;
  health_state: HealthState;
  last_error_class: string | null;
  last_error_message: string | null;
  last_error_at: string | null;
  last_success_at: string | null;
  circuit_open: boolean;
  route_roles: ModelRole[];
  created_at: string;
  updated_at: string;
}

export interface AIProvider {
  id: string;
  provider_type: ProviderType;
  provider_label: string;
  display_name: string;
  base_url: string | null;
  effective_base_url: string;
  enabled: boolean;
  has_key: boolean;
  key_masked: string | null;
  key_updated_at: string | null;
  health_state: HealthState;
  connection_status: ConnectionStatus;
  consecutive_failures: number;
  last_error_class: string | null;
  last_error_message: string | null;
  last_error_at: string | null;
  last_success_at: string | null;
  last_tested_at: string | null;
  verification: "mocked" | "live";
  models: AIModel[];
  created_at: string;
  updated_at: string;
}

export interface ModelInput {
  model_identifier: string;
  display_name?: string | null;
  context_window?: number | null;
  input_price_per_mtok?: string | null;
  output_price_per_mtok?: string | null;
  supports_json?: boolean;
  capabilities?: ModelCapability[];
  enabled?: boolean;
}

export interface ProviderCreateInput {
  provider_type: ProviderType;
  display_name: string;
  api_key?: string;
  base_url?: string | null;
  models: ModelInput[];
}

export interface ProviderUpdateInput {
  display_name?: string;
  base_url?: string | null;
  enabled?: boolean;
}

export interface ConnectionTestResult {
  ok: boolean;
  provider_id: string;
  model_identifier: string;
  latency_ms: number;
  error_class: string | null;
  error_hint: string | null;
  message: string;
  http_status: number | null;
  health_state: HealthState;
  tested_at: string;
}

export interface DiscoveredModel {
  id: string;
  display_name: string | null;
  context_window: number | null;
  configured: boolean;
}

export interface DiscoveredModels {
  ok: boolean;
  models: DiscoveredModel[];
  error_class: string | null;
  message: string | null;
}

export interface RouteEntry {
  position: number;
  model_id: string;
  model_identifier: string;
  model_display_name: string | null;
  provider_id: string;
  provider_name: string;
  provider_type: ProviderType;
  available: boolean;
  unavailable_reason: string | null;
  health_state: HealthState;
}

export interface RoleRoute {
  role: ModelRole;
  uses_default: boolean;
  entries: RouteEntry[];
}

export interface RoutingPolicy {
  max_retries: number;
  max_retry_after_seconds: number;
  fallback_on_rate_limit: boolean;
  fallback_on_quota_exhausted: boolean;
}

export interface RoutingAttempt {
  provider_name: string;
  model_identifier: string;
  model_id: string | null;
  outcome: "success" | "retry" | "fallback" | "error" | "skipped";
  attempt: number | null;
  error_class: string | null;
  message: string | null;
  http_status: number | null;
  latency_ms: number | null;
}

export interface RoutingTestResult {
  ok: boolean;
  role: ModelRole;
  provider_name: string | null;
  model_identifier: string | null;
  latency_ms: number | null;
  used_fallback: boolean;
  error_code: string | null;
  error_class: string | null;
  message: string | null;
  attempts: RoutingAttempt[];
}

export interface ProviderHealth {
  provider_id: string;
  display_name: string;
  provider_type: ProviderType;
  enabled: boolean;
  health_state: HealthState;
  last_error_class: string | null;
  last_error_message: string | null;
  last_error_at: string | null;
  last_success_at: string | null;
  last_tested_at: string | null;
  window_hours: number;
  calls: number;
  successes: number;
  failures: number;
  success_rate: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
}

export interface UsageRow {
  key: string;
  label: string;
  calls: number;
  successes: number;
  failures: number;
  input_tokens: number;
  output_tokens: number;
  est_cost_usd: string | null;
  avg_latency_ms: number | null;
}

export type UsageGroupBy = "provider" | "model" | "day" | "purpose" | "outcome";

export interface UsageSummary {
  date_from: string;
  date_to: string;
  group_by: UsageGroupBy;
  rows: UsageRow[];
  totals: UsageRow;
}

export interface UsageRecord {
  id: string;
  created_at: string;
  call_id: string;
  provider_id: string | null;
  provider_name: string;
  provider_type: string;
  model_identifier: string;
  role: string;
  purpose: string;
  attempt: number;
  outcome: string;
  error_class: string | null;
  http_status: number | null;
  latency_ms: number;
  input_tokens: number | null;
  output_tokens: number | null;
  est_cost_usd: string | null;
}

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: { fields?: FieldError[] } & Record<string, unknown>;
    request_id: string | null;
  };
}
