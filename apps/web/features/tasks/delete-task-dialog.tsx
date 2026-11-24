"use client";

import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ui/dialog";
import { useDeleteTask } from "@/features/tasks/hooks";
import { errorMessage } from "@/lib/api-client";
import type { ResearchTask } from "@/types/api";

interface Props {
  task: Pick<ResearchTask, "id" | "title"> | null;
  onOpenChange: (open: boolean) => void;
  onDeleted?: () => void;
}

export function DeleteTaskDialog({ task, onOpenChange, onDeleted }: Props) {
  const del = useDeleteTask();
  return (
    <ConfirmDialog
      open={task !== null}
      onOpenChange={(open) => {
        if (!open) del.reset();
        onOpenChange(open);
      }}
      title="Delete research task?"
      description={
        <>
          <span className="font-medium text-foreground">{task?.title}</span> will be permanently
          deleted. This cannot be undone.
        </>
      }
      confirmLabel="Delete task"
      pendingLabel="Deleting…"
      destructive
      pending={del.isPending}
      error={del.isError ? errorMessage(del.error) : null}
      onConfirm={() => {
        if (!task) return;
        del.mutate(task.id, {
          onSuccess: () => {
            toast.success("Research task deleted");
            onOpenChange(false);
            onDeleted?.();
          },
        });
      }}
    />
  );
}
