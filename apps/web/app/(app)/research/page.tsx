"use client";

import { Plus, Search } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { TaskBrowser } from "@/features/tasks/task-browser";
import { TASK_STATUSES } from "@/types/api";

export default function ResearchPage() {
  return (
    <>
      <PageHeader
        title="Research"
        description="Research tasks you have created. Draft tasks can be edited until a plan is generated."
        actions={
          <Button asChild>
            <Link href="/research/new">
              <Plus /> New research task
            </Link>
          </Button>
        }
      />
      <TaskBrowser
        statuses={TASK_STATUSES}
        emptyIcon={Search}
        emptyTitle="No research tasks yet"
        emptyDescription="Describe something you want researched. You'll be able to review a plan before anything runs."
        emptyAction={
          <Button asChild size="sm">
            <Link href="/research/new">
              <Plus /> Create your first task
            </Link>
          </Button>
        }
      />
    </>
  );
}
