import type { HealthState, ModelCapability, ModelRole } from "@/types/api";

type Tone = "neutral" | "info" | "warning" | "success" | "danger" | "accent";

export const HEALTH_META: Record<HealthState, { label: string; tone: Tone; hint: string }> = {
  unknown: { label: "Not tested", tone: "neutral", hint: "Run a connection test to check it." },
  healthy: { label: "Healthy", tone: "success", hint: "The last call succeeded." },
  degraded: { label: "Degraded", tone: "warning", hint: "Recent calls failed temporarily." },
  down: { label: "Down", tone: "danger", hint: "Several calls in a row failed." },
  invalid_credentials: {
    label: "Key rejected",
    tone: "danger",
    hint: "The provider rejected the API key. Replace it.",
  },
  quota_exhausted: {
    label: "Out of credit",
    tone: "danger",
    hint: "The account has no remaining credit or quota.",
  },
  misconfigured: {
    label: "Misconfigured",
    tone: "danger",
    hint: "The model was not found. Check the model ID.",
  },
};

export function healthMeta(state: string) {
  return HEALTH_META[state as HealthState] ?? HEALTH_META.unknown;
}

export const ROLE_META: Record<ModelRole, { label: string; hint: string }> = {
  default: { label: "Default", hint: "Used for every task unless a role has its own chain." },
  planner: { label: "Planner", hint: "Turns research objectives into plans." },
  researcher: { label: "Researcher", hint: "Decides what to search and which sources to read." },
  extractor: { label: "Extractor", hint: "Pulls structured fields out of pages." },
  verifier: { label: "Verifier", hint: "Cross-checks extracted values." },
  summarizer: { label: "Summarizer", hint: "Writes reports and summaries." },
};

export const CAPABILITY_LABELS: Record<ModelCapability, string> = {
  json: "JSON",
  vision: "Vision",
  tools: "Tools",
  reasoning: "Reasoning",
};

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

export const ERROR_CLASS_LABELS: Record<string, string> = {
  timeout: "Timeout",
  network: "Network error",
  rate_limited: "Rate limited",
  server_error: "Provider error",
  auth: "Key rejected",
  quota_exhausted: "Out of credit",
  model_not_found: "Model not found",
  invalid_request: "Invalid request",
  context_length: "Too long",
  content_policy: "Content policy",
  invalid_response: "Unreadable reply",
  unknown: "Unknown error",
};

export const OUTCOME_META: Record<string, { label: string; tone: Tone }> = {
  success: { label: "Success", tone: "success" },
  retry: { label: "Retried", tone: "warning" },
  fallback: { label: "Fell back", tone: "warning" },
  error: { label: "Failed", tone: "danger" },
  skipped: { label: "Skipped", tone: "neutral" },
};

const FAILED_OUTCOME: { label: string; tone: Tone } = { label: "Failed", tone: "danger" };

export function outcomeMeta(outcome: string): { label: string; tone: Tone } {
  return OUTCOME_META[outcome] ?? FAILED_OUTCOME;
}

export const PURPOSE_LABELS: Record<string, string> = {
  completion: "Completion",
  connection_test: "Connection test",
  routing_test: "Routing test",
};

export function formatCost(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  if (n === 0) return "$0";
  return n < 0.01 ? `$${n.toFixed(5)}` : `$${n.toFixed(2)}`;
}

export function formatPercent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

export function formatMs(value: number | null): string {
  if (value === null) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}
