import { describe, expect, it } from "vitest";

import { toTaskInput, validateTaskForm } from "@/features/tasks/validation";

const valid = {
  title: "India AI startups",
  objective: "Find 50 AI startups in India",
  description: "",
  projectId: "",
};

describe("validateTaskForm", () => {
  it("accepts a valid task", () => {
    expect(validateTaskForm(valid)).toEqual({});
  });

  it("requires a title and a long-enough objective", () => {
    const errors = validateTaskForm({ ...valid, title: "   ", objective: "short" });
    expect(errors.title).toMatch(/required/i);
    expect(errors.objective).toMatch(/at least 10/);
  });

  it("enforces maximum lengths", () => {
    const errors = validateTaskForm({ ...valid, title: "x".repeat(201) });
    expect(errors.title).toMatch(/at most 200/);
  });
});

describe("toTaskInput", () => {
  it("trims values and converts blanks to null", () => {
    expect(
      toTaskInput({ title: "  T  ", objective: "  objective text  ", description: "  ", projectId: "" }),
    ).toEqual({ title: "T", objective: "objective text", description: null, project_id: null });
  });
});
