"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { useTask, useUpdateTask } from "@/features/tasks/hooks";
import { TaskForm } from "@/features/tasks/task-form";
import { errorMessage } from "@/lib/api-client";
import { Lock } from "lucide-react";

export default function EditTaskPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const task = useTask(id);
  const update = useUpdateTask(id);

  let body: React.ReactNode;
  if (task.isPending) body = <Skeleton className="h-96 w-full" />;
  else if (task.isError)
    body = <ErrorState message={errorMessage(task.error)} onRetry={() => void task.refetch()} />;
  else if (!task.data.is_editable)
    body = (
      <Card>
        <EmptyState
          icon={Lock}
          title="This task can no longer be edited"
          description="Only draft research tasks can be edited."
          action={
            <Button asChild variant="outline" size="sm">
              <Link href={`/research/${id}`}>Back to task</Link>
            </Button>
          }
        />
      </Card>
    );
  else
    body = (
      <Card>
        <CardContent className="py-6">
          <TaskForm
            initial={{
              title: task.data.title,
              objective: task.data.objective,
              description: task.data.description ?? "",
              projectId: task.data.project_id ?? "",
            }}
            submitLabel="Save changes"
            onCancel={() => router.push(`/research/${id}`)}
            onSubmit={async (input) => {
              await update.mutateAsync(input);
              toast.success("Changes saved");
              router.push(`/research/${id}`);
            }}
          />
        </CardContent>
      </Card>
    );

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Edit research task"
        breadcrumb={{ href: `/research/${id}`, label: task.data?.title ?? "Task" }}
      />
      {body}
    </div>
  );
}
