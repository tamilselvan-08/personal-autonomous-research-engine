"use client";

import { History } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { TaskBrowser } from "@/features/tasks/task-browser";
import { HISTORY_STATUSES } from "@/lib/status";

export default function HistoryPage() {
  return (
    <>
      <PageHeader
        title="History"
        description="Research tasks that have finished: completed, failed or cancelled."
      />
      <TaskBrowser
        statuses={HISTORY_STATUSES}
        emptyIcon={History}
        emptyTitle="No finished research yet"
        emptyDescription="Tasks appear here once they complete, fail or are cancelled. Running research becomes available in a later release."
      />
    </>
  );
}
