import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StatusBadge } from "@/features/tasks/status-badge";
import { TaskForm } from "@/features/tasks/task-form";
import { ApiError } from "@/lib/api-client";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  // The form loads projects for its picker.
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            items: [{ id: "p1", name: "Clients", description: null, task_count: 0, created_at: "", updated_at: "" }],
            total: 1,
            page: 1,
            page_size: 100,
            pages: 1,
          }),
          { status: 200 },
        ),
      ),
    ),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("TaskForm", () => {
  it("shows client-side validation errors and does not submit", async () => {
    const onSubmit = vi.fn();
    render(<TaskForm submitLabel="Create draft" onSubmit={onSubmit} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    expect(await screen.findByText("Title is required.")).toBeInTheDocument();
    expect(screen.getByText("Describe what you want researched.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits trimmed values including the chosen project", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<TaskForm submitLabel="Create draft" onSubmit={onSubmit} />, { wrapper });
    await userEvent.type(screen.getByLabelText(/Title/), "  AI startups  ");
    await userEvent.type(screen.getByLabelText(/Research objective/), "Find 50 AI startups in India");
    await screen.findByRole("option", { name: "Clients" });
    await userEvent.selectOptions(screen.getByLabelText(/Project/), "p1");
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        title: "AI startups",
        objective: "Find 50 AI startups in India",
        description: null,
        project_id: "p1",
      }),
    );
  });

  it("shows server field errors next to the field", async () => {
    const onSubmit = vi.fn().mockRejectedValue(
      new ApiError(422, "VALIDATION_ERROR", "Request validation failed.", {
        fields: [{ loc: ["body", "project_id"], msg: "Project does not exist.", type: "value_error" }],
      }),
    );
    render(
      <TaskForm
        submitLabel="Save"
        initial={{ title: "T", objective: "A long enough objective" }}
        onSubmit={onSubmit}
      />,
      { wrapper },
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Project does not exist.")).toBeInTheDocument();
  });

  it("shows a form-level message for other errors", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(new ApiError(409, "TASK_NOT_EDITABLE", "Only draft research tasks can be edited."));
    render(
      <TaskForm submitLabel="Save" initial={{ title: "T", objective: "A long enough objective" }} onSubmit={onSubmit} />,
      { wrapper },
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only draft research tasks can be edited.");
  });
});

describe("StatusBadge", () => {
  it("renders a readable label, not just a colour", () => {
    render(<StatusBadge status="awaiting_approval" />);
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
  });
});
