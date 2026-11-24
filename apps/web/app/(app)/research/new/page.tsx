"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { useCreateTask } from "@/features/tasks/hooks";
import { TaskForm } from "@/features/tasks/task-form";

function NewTask() {
  const router = useRouter();
  const params = useSearchParams();
  const create = useCreateTask();
  return (
    <Card>
      <CardContent className="py-6">
        <TaskForm
          initial={{ projectId: params.get("project") ?? "" }}
          submitLabel="Create draft"
          onCancel={() => router.back()}
          onSubmit={async (input) => {
            const task = await create.mutateAsync(input);
            toast.success("Draft research task created");
            router.push(`/research/${task.id}`);
          }}
        />
      </CardContent>
    </Card>
  );
}

export default function NewTaskPage() {
  return (
    <div className="max-w-3xl">
      <PageHeader
        title="New research task"
        description="Start with a clear objective. The task is saved as a draft; nothing runs yet."
        breadcrumb={{ href: "/research", label: "Research" }}
      />
      <Suspense>
        <NewTask />
      </Suspense>
    </div>
  );
}
