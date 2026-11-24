"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { useProjectOptions } from "@/features/projects/hooks";
import {
  TASK_LIMITS,
  toTaskInput,
  validateTaskForm,
  type TaskFormErrors,
  type TaskFormValues,
} from "@/features/tasks/validation";
import { ApiError, errorMessage } from "@/lib/api-client";
import type { TaskInput } from "@/types/api";

interface TaskFormProps {
  initial?: Partial<TaskFormValues>;
  submitLabel: string;
  onSubmit: (input: TaskInput) => Promise<unknown>;
  onCancel?: () => void;
}

export function TaskForm({ initial, submitLabel, onSubmit, onCancel }: TaskFormProps) {
  const projects = useProjectOptions();
  const [values, setValues] = useState<TaskFormValues>({
    title: initial?.title ?? "",
    objective: initial?.objective ?? "",
    description: initial?.description ?? "",
    projectId: initial?.projectId ?? "",
  });
  const [errors, setErrors] = useState<TaskFormErrors & { project_id?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const set = (key: keyof TaskFormValues) => (value: string) =>
    setValues((v) => ({ ...v, [key]: value }));

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const clientErrors = validateTaskForm(values);
    setErrors(clientErrors);
    if (Object.keys(clientErrors).length) return;
    setPending(true);
    try {
      await onSubmit(toTaskInput(values));
    } catch (error) {
      if (error instanceof ApiError && error.fieldErrors.length) setErrors(error.fieldMessages());
      else setFormError(errorMessage(error));
    } finally {
      setPending(false);
    }
  }

  const objectiveLength = values.objective.trim().length;

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      <Field id="title" label="Title" error={errors.title} required>
        <Input
          id="title"
          value={values.title}
          onChange={(e) => set("title")(e.target.value)}
          placeholder="e.g. AI startups in India"
          maxLength={TASK_LIMITS.titleMax}
          aria-invalid={!!errors.title}
          aria-describedby={errors.title ? "title-error" : undefined}
          autoFocus
        />
      </Field>

      <Field
        id="objective"
        label="Research objective"
        error={errors.objective}
        hint={
          <span className="flex justify-between gap-4">
            <span>Describe what to find, which fields to collect, and how to verify them.</span>
            <span className="tabular-nums">
              {objectiveLength}/{TASK_LIMITS.objectiveMax}
            </span>
          </span>
        }
        required
      >
        <Textarea
          id="objective"
          rows={6}
          value={values.objective}
          onChange={(e) => set("objective")(e.target.value)}
          placeholder="Research the top 50 AI startups in India. Collect company name, website, founders, funding, products, headquarters and official LinkedIn page. Verify key facts using at least two sources."
          aria-invalid={!!errors.objective}
          aria-describedby={errors.objective ? "objective-error" : "objective-hint"}
        />
      </Field>

      <Field
        id="description"
        label="Notes"
        error={errors.description}
        hint="Optional. Context for yourself, such as who the research is for."
      >
        <Textarea
          id="description"
          rows={3}
          value={values.description}
          onChange={(e) => set("description")(e.target.value)}
          aria-invalid={!!errors.description}
        />
      </Field>

      <Field
        id="project"
        label="Project"
        error={errors.project_id}
        hint={projects.isError ? "Projects could not be loaded." : "Optional."}
      >
        <NativeSelect
          id="project"
          value={values.projectId}
          onChange={(e) => set("projectId")(e.target.value)}
          disabled={projects.isPending}
          aria-invalid={!!errors.project_id}
        >
          <option value="">No project</option>
          {projects.data?.items.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </NativeSelect>
      </Field>

      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}

      <div className="flex gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : submitLabel}
        </Button>
        {onCancel ? (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
    </form>
  );
}
