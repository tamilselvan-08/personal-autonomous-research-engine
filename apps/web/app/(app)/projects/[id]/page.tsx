"use client";

import { Pencil, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { ErrorState, Skeleton } from "@/components/ui/misc";
import { useProject } from "@/features/projects/hooks";
import { DeleteProjectDialog, ProjectDialog } from "@/features/projects/project-dialogs";
import { TaskBrowser } from "@/features/tasks/task-browser";
import { ApiError, errorMessage } from "@/lib/api-client";
import { TASK_STATUSES } from "@/types/api";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const project = useProject(id);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  if (project.isPending) return <Skeleton className="h-64 w-full" />;
  if (project.isError) {
    const notFound = project.error instanceof ApiError && project.error.status === 404;
    return (
      <ErrorState
        title={notFound ? "Project not found" : "Couldn't load this project"}
        message={notFound ? "It may have been deleted." : errorMessage(project.error)}
        onRetry={notFound ? undefined : () => void project.refetch()}
      />
    );
  }

  const p = project.data;
  const newTaskHref = `/research/new?project=${p.id}`;
  return (
    <>
      <PageHeader
        title={p.name}
        description={p.description ?? undefined}
        breadcrumb={{ href: "/projects", label: "Projects" }}
        actions={
          <>
            <Button variant="outline" onClick={() => setEditOpen(true)}>
              <Pencil /> Edit
            </Button>
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 /> Delete
            </Button>
            <Button asChild>
              <Link href={newTaskHref}>
                <Plus /> New task
              </Link>
            </Button>
          </>
        }
      />
      <TaskBrowser
        statuses={TASK_STATUSES}
        fixedProjectId={p.id}
        emptyIcon={Search}
        emptyTitle="No tasks in this project"
        emptyDescription="Create a research task here, or assign an existing draft to this project from its edit page."
        emptyAction={
          <Button asChild size="sm">
            <Link href={newTaskHref}>
              <Plus /> New task in {p.name}
            </Link>
          </Button>
        }
      />
      <ProjectDialog open={editOpen} onOpenChange={setEditOpen} project={p} />
      <DeleteProjectDialog
        project={deleteOpen ? p : null}
        onOpenChange={setDeleteOpen}
        onDeleted={() => router.replace("/projects")}
      />
    </>
  );
}
