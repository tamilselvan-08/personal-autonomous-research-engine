"use client";

import { Lock, Pencil, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/misc";
import { DeleteTaskDialog } from "@/features/tasks/delete-task-dialog";
import { useTask } from "@/features/tasks/hooks";
import { StatusBadge } from "@/features/tasks/status-badge";
import { ApiError, errorMessage } from "@/lib/api-client";
import { STATUS_META } from "@/lib/status";
import { formatDateTime } from "@/lib/utils";

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const task = useTask(id);
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (task.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (task.isError) {
    const notFound = task.error instanceof ApiError && task.error.status === 404;
    return (
      <ErrorState
        title={notFound ? "Research task not found" : "Couldn't load this task"}
        message={notFound ? "It may have been deleted." : errorMessage(task.error)}
        onRetry={notFound ? undefined : () => void task.refetch()}
      />
    );
  }

  const t = task.data;
  return (
    <>
      <PageHeader
        title={t.title}
        breadcrumb={{ href: "/research", label: "Research" }}
        actions={
          <>
            {t.is_editable ? (
              <Button variant="outline" asChild>
                <Link href={`/research/${t.id}/edit`}>
                  <Pencil /> Edit
                </Link>
              </Button>
            ) : null}
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              disabled={!t.is_deletable}
              title={t.is_deletable ? undefined : "Cancel the running research before deleting"}
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 /> Delete
            </Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Objective</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{t.objective}</p>
            </CardContent>
          </Card>
          {t.description ? (
            <Card>
              <CardHeader>
                <CardTitle>Notes</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                  {t.description}
                </p>
              </CardContent>
            </Card>
          ) : null}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="size-4 text-muted-foreground" aria-hidden /> Research plan
              </CardTitle>
              <CardDescription>
                Coming soon. In a later release PARE will turn this objective into a structured
                plan — queries, sources, fields and limits — for you to review and approve before
                any research runs.
              </CardDescription>
            </CardHeader>
          </Card>
        </div>

        <Card className="h-fit">
          <CardContent>
            <dl className="space-y-4">
              <Meta label="Status">
                <div className="space-y-1.5">
                  <StatusBadge status={t.status} />
                  <p className="text-[13px] text-muted-foreground">{STATUS_META[t.status].hint}</p>
                </div>
              </Meta>
              <Meta label="Project">
                {t.project ? (
                  <Link href={`/projects/${t.project.id}`} className="hover:underline">
                    {t.project.name}
                  </Link>
                ) : (
                  <span className="text-muted-foreground">None</span>
                )}
              </Meta>
              <Meta label="Created">{formatDateTime(t.created_at)}</Meta>
              <Meta label="Last updated">{formatDateTime(t.updated_at)}</Meta>
              {!t.is_editable ? (
                <p className="flex items-start gap-2 rounded-md bg-muted p-2 text-[13px] text-muted-foreground">
                  <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  Only draft tasks can be edited.
                </p>
              ) : null}
            </dl>
          </CardContent>
        </Card>
      </div>

      <DeleteTaskDialog
        task={confirmDelete ? t : null}
        onOpenChange={setConfirmDelete}
        onDeleted={() => router.replace("/research")}
      />
    </>
  );
}
