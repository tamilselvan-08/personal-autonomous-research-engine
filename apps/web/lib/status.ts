import type { TaskStatus } from "@/types/api";

export type StatusTone = "neutral" | "info" | "warning" | "success" | "danger" | "accent";

export const STATUS_META: Record<TaskStatus, { label: string; tone: StatusTone; hint: string }> = {
  draft: { label: "Draft", tone: "neutral", hint: "Being written. Not yet planned." },
  planning: { label: "Planning", tone: "info", hint: "A research plan is being generated." },
  awaiting_approval: {
    label: "Awaiting approval",
    tone: "warning",
    hint: "Plan ready. Review and approve it to run.",
  },
  approved: { label: "Approved", tone: "accent", hint: "Plan approved and ready to run." },
  queued: { label: "Queued", tone: "neutral", hint: "Waiting for a worker." },
  running: { label: "Running", tone: "info", hint: "Research is in progress." },
  paused: { label: "Paused", tone: "warning", hint: "Execution is paused." },
  completed: { label: "Completed", tone: "success", hint: "Research finished." },
  failed: { label: "Failed", tone: "danger", hint: "Execution stopped with an error." },
  cancelled: { label: "Cancelled", tone: "neutral", hint: "Execution was cancelled." },
};

export const HISTORY_STATUSES: TaskStatus[] = ["completed", "failed", "cancelled"];

const ACTION_LABELS: Record<string, string> = {
  "task.created": "Created task",
  "task.updated": "Edited task",
  "task.deleted": "Deleted task",
  "project.created": "Created project",
  "project.updated": "Edited project",
  "project.deleted": "Deleted project",
};

export function describeAction(action: string): string {
  return ACTION_LABELS[action] ?? action;
}
