"use client";

import { Search, SearchX, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { Pagination } from "@/components/ui/pagination";
import { useProjectOptions } from "@/features/projects/hooks";
import { useTaskList } from "@/features/tasks/hooks";
import { TaskTable } from "@/features/tasks/task-table";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { errorMessage } from "@/lib/api-client";
import { STATUS_META } from "@/lib/status";
import type { TaskSort, TaskStatus } from "@/types/api";

const PAGE_SIZE = 20;

interface TaskBrowserProps {
  /** Statuses the user may filter by. The list never shows other statuses. */
  statuses: readonly TaskStatus[];
  emptyIcon: LucideIcon;
  emptyTitle: string;
  emptyDescription: ReactNode;
  emptyAction?: ReactNode;
  fixedProjectId?: string;
}

export function TaskBrowser({
  statuses,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  emptyAction,
  fixedProjectId,
}: TaskBrowserProps) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<TaskStatus | "">("");
  const [projectId, setProjectId] = useState("");
  const [sort, setSort] = useState<TaskSort>("updated_desc");
  const [page, setPage] = useState(1);
  const q = useDebouncedValue(search.trim(), 300);
  const projects = useProjectOptions();

  const effectiveProject = fixedProjectId ?? (projectId || undefined);
  const list = useTaskList({
    page,
    pageSize: PAGE_SIZE,
    q: q || undefined,
    status: status ? [status] : [...statuses],
    projectId: effectiveProject,
    sort,
  });

  const filtered = Boolean(q || status || (!fixedProjectId && projectId));
  const resetPage = () => setPage(1);

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-2 border-b p-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            aria-label="Search tasks"
            placeholder="Search title or objective…"
            className="pl-8"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              resetPage();
            }}
          />
        </div>
        <div className="grid grid-cols-2 gap-2 md:flex">
          <NativeSelect
            aria-label="Filter by status"
            className="md:w-44"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as TaskStatus | "");
              resetPage();
            }}
          >
            <option value="">All statuses</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {STATUS_META[s].label}
              </option>
            ))}
          </NativeSelect>
          {!fixedProjectId ? (
            <NativeSelect
              aria-label="Filter by project"
              className="md:w-44"
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
                resetPage();
              }}
            >
              <option value="">All projects</option>
              {projects.data?.items.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </NativeSelect>
          ) : null}
          <NativeSelect
            aria-label="Sort"
            className="col-span-2 md:col-span-1 md:w-48"
            value={sort}
            onChange={(e) => setSort(e.target.value as TaskSort)}
          >
            <option value="updated_desc">Recently updated</option>
            <option value="created_desc">Newest first</option>
            <option value="created_asc">Oldest first</option>
            <option value="title_asc">Title A–Z</option>
          </NativeSelect>
        </div>
      </div>

      {list.isPending ? (
        <div className="space-y-3 p-4" aria-busy>
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : list.isError ? (
        <div className="p-4">
          <ErrorState message={errorMessage(list.error)} onRetry={() => void list.refetch()} />
        </div>
      ) : list.data.items.length === 0 ? (
        filtered ? (
          <EmptyState
            icon={SearchX}
            title="No matching tasks"
            description="Try a different search term or clear the filters."
          />
        ) : (
          <EmptyState
            icon={emptyIcon}
            title={emptyTitle}
            description={emptyDescription}
            action={emptyAction}
          />
        )
      ) : (
        <>
          <TaskTable tasks={list.data.items} showProject={!fixedProjectId} />
          <Pagination
            page={list.data.page}
            pages={list.data.pages}
            total={list.data.total}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </>
      )}
    </Card>
  );
}
