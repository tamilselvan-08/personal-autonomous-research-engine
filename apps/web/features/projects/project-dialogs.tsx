"use client";

import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { useDeleteProject, useSaveProject } from "@/features/projects/hooks";
import { ApiError, errorMessage } from "@/lib/api-client";
import { pluralize } from "@/lib/utils";
import type { Project } from "@/types/api";

interface ProjectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  project?: Project | null;
  onSaved?: (project: Project) => void;
}

function ProjectFormBody({
  project,
  onDone,
  onSaved,
}: {
  project?: Project | null;
  onDone: () => void;
  onSaved?: (project: Project) => void;
}) {
  const save = useSaveProject(project?.id);
  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    if (!name.trim()) {
      setErrors({ name: "Name is required." });
      return;
    }
    setErrors({});
    try {
      const saved = await save.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
      });
      toast.success(project ? "Project updated" : "Project created");
      onSaved?.(saved);
      onDone();
    } catch (error) {
      if (error instanceof ApiError && error.code === "PROJECT_NAME_TAKEN") {
        setErrors({ name: error.message });
      } else if (error instanceof ApiError && error.fieldErrors.length) {
        setErrors(error.fieldMessages());
      } else {
        setFormError(errorMessage(error));
      }
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <Field id="project-name" label="Name" error={errors.name} required>
        <Input
          id="project-name"
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          aria-invalid={!!errors.name}
          autoFocus
        />
      </Field>
      <Field id="project-description" label="Description" error={errors.description} hint="Optional.">
        <Textarea
          id="project-description"
          rows={3}
          maxLength={2000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : project ? "Save changes" : "Create project"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function ProjectDialog({ open, onOpenChange, project, onSaved }: ProjectDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{project ? "Edit project" : "New project"}</DialogTitle>
          <DialogDescription>Projects group related research tasks.</DialogDescription>
        </DialogHeader>
        {/* Remount per open so the form starts from the current project values. */}
        {open ? (
          <ProjectFormBody
            key={project?.id ?? "new"}
            project={project}
            onSaved={onSaved}
            onDone={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export function DeleteProjectDialog({
  project,
  onOpenChange,
  onDeleted,
}: {
  project: Project | null;
  onOpenChange: (open: boolean) => void;
  onDeleted?: () => void;
}) {
  const del = useDeleteProject();
  const hasTasks = (project?.task_count ?? 0) > 0;
  return (
    <ConfirmDialog
      open={project !== null}
      onOpenChange={(open) => {
        if (!open) del.reset();
        onOpenChange(open);
      }}
      title="Delete project?"
      description={
        hasTasks ? (
          <>
            <span className="font-medium text-foreground">{project?.name}</span> contains{" "}
            {pluralize(project?.task_count ?? 0, "research task")}. The tasks will be kept and
            moved to “No project”.
          </>
        ) : (
          <>
            <span className="font-medium text-foreground">{project?.name}</span> will be
            permanently deleted.
          </>
        )
      }
      confirmLabel="Delete project"
      pendingLabel="Deleting…"
      destructive
      pending={del.isPending}
      error={del.isError ? errorMessage(del.error) : null}
      onConfirm={() => {
        if (!project) return;
        del.mutate(
          { id: project.id, detachTasks: hasTasks },
          {
            onSuccess: () => {
              toast.success("Project deleted");
              onOpenChange(false);
              onDeleted?.();
            },
          },
        );
      }}
    />
  );
}
