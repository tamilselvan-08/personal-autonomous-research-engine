import { Badge } from "@/components/ui/badge";
import { STATUS_META } from "@/lib/status";
import { cn } from "@/lib/utils";
import type { TaskStatus } from "@/types/api";

const DOT: Record<string, string> = {
  neutral: "bg-muted-foreground",
  info: "bg-info",
  warning: "bg-warning",
  success: "bg-success",
  danger: "bg-destructive",
  accent: "bg-primary",
};

export function StatusBadge({ status, className }: { status: TaskStatus; className?: string }) {
  const meta = STATUS_META[status];
  return (
    <Badge tone={meta.tone} className={className} title={meta.hint}>
      <span aria-hidden className={cn("size-1.5 rounded-full", DOT[meta.tone])} />
      {meta.label}
    </Badge>
  );
}
