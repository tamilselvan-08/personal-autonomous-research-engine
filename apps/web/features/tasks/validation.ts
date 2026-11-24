import type { TaskInput } from "@/types/api";

export const TASK_LIMITS = {
  titleMax: 200,
  objectiveMin: 10,
  objectiveMax: 5000,
  descriptionMax: 10000,
} as const;

export interface TaskFormValues {
  title: string;
  objective: string;
  description: string;
  projectId: string;
}

export type TaskFormErrors = Partial<Record<"title" | "objective" | "description", string>>;

/** Client-side checks mirroring the API schema, for instant feedback. The API stays authoritative. */
export function validateTaskForm(values: TaskFormValues): TaskFormErrors {
  const errors: TaskFormErrors = {};
  const title = values.title.trim();
  const objective = values.objective.trim();
  if (!title) errors.title = "Title is required.";
  else if (title.length > TASK_LIMITS.titleMax)
    errors.title = `Title must be at most ${TASK_LIMITS.titleMax} characters.`;
  if (!objective) errors.objective = "Describe what you want researched.";
  else if (objective.length < TASK_LIMITS.objectiveMin)
    errors.objective = `Objective must be at least ${TASK_LIMITS.objectiveMin} characters.`;
  else if (objective.length > TASK_LIMITS.objectiveMax)
    errors.objective = `Objective must be at most ${TASK_LIMITS.objectiveMax} characters.`;
  if (values.description.length > TASK_LIMITS.descriptionMax)
    errors.description = `Notes must be at most ${TASK_LIMITS.descriptionMax} characters.`;
  return errors;
}

export function toTaskInput(values: TaskFormValues): TaskInput {
  const description = values.description.trim();
  return {
    title: values.title.trim(),
    objective: values.objective.trim(),
    description: description || null,
    project_id: values.projectId || null,
  };
}
