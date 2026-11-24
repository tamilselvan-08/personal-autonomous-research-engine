"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity as ActivityIcon,
  CheckCircle2,
  CircleAlert,
  FileText,
  Layers,
  Plus,
  Search,
} from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { useTaskList } from "@/features/tasks/hooks";
import { StatusBadge } from "@/features/tasks/status-badge";
import { useAuth } from "@/hooks/use-auth";
import { api, queryKeys } from "@/lib/api";
import { errorMessage } from "@/lib/api-client";
import { describeAction } from "@/lib/status";
import { formatDateTime, formatRelative } from "@/lib/utils";

function StatCard({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: number | undefined;
  icon: typeof Layers;
  hint: string;
}) {
  return (
    <Card>
      <CardContent className="space-y-2">
        <div className="flex items-center justify-between text-muted-foreground">
          <span className="text-[13px] font-medium">{label}</span>
          <Icon className="size-4" aria-hidden />
        </div>
        {value === undefined ? (
          <Skeleton className="h-8 w-12" />
        ) : (
          <p className="text-2xl font-semibold tabular-nums">{value}</p>
        )}
        <p className="text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );
}

function RecentTasks() {
  const tasks = useTaskList({ page: 1, pageSize: 5, sort: "updated_desc" });
  if (tasks.isPending) return <Skeleton className="m-5 h-24" />;
  if (tasks.isError)
    return (
      <div className="p-4">
        <ErrorState message={errorMessage(tasks.error)} onRetry={() => void tasks.refetch()} />
      </div>
    );
  return (
    <ul className="divide-y">
      {tasks.data.items.map((t) => (
        <li key={t.id} className="flex items-center gap-3 px-5 py-3">
          <div className="min-w-0 flex-1">
            <Link href={`/research/${t.id}`} className="block truncate text-sm font-medium hover:underline">
              {t.title}
            </Link>
            <p className="text-xs text-muted-foreground">Updated {formatRelative(t.updated_at)}</p>
          </div>
          <StatusBadge status={t.status} />
        </li>
      ))}
    </ul>
  );
}

function RecentActivity() {
  const activity = useQuery({
    queryKey: queryKeys.activity,
    queryFn: () => api.tasks.recentActivity(8),
  });
  if (activity.isPending) return <Skeleton className="m-5 h-24" />;
  if (activity.isError)
    return (
      <div className="p-4">
        <ErrorState message={errorMessage(activity.error)} onRetry={() => void activity.refetch()} />
      </div>
    );
  if (activity.data.length === 0)
    return <p className="px-5 py-6 text-sm text-muted-foreground">No activity yet.</p>;
  return (
    <ol className="space-y-3 px-5 py-4">
      {activity.data.map((e) => {
        const title = typeof e.data.title === "string" ? e.data.title : typeof e.data.name === "string" ? e.data.name : null;
        const href =
          e.entity_id && e.action !== "task.deleted" && e.action !== "project.deleted"
            ? e.entity_type === "research_task"
              ? `/research/${e.entity_id}`
              : `/projects/${e.entity_id}`
            : null;
        return (
          <li key={e.id} className="flex gap-3 text-sm">
            <span aria-hidden className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/60" />
            <div className="min-w-0">
              <p className="truncate">
                <span className="text-muted-foreground">{describeAction(e.action)}</span>{" "}
                {title ? (
                  href ? (
                    <Link href={href} className="font-medium hover:underline">
                      {title}
                    </Link>
                  ) : (
                    <span className="font-medium">{title}</span>
                  )
                ) : null}
              </p>
              <time className="text-xs text-muted-foreground" dateTime={e.created_at} title={formatDateTime(e.created_at)}>
                {formatRelative(e.created_at)}
              </time>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const stats = useQuery({ queryKey: queryKeys.taskStats, queryFn: api.tasks.stats });
  const isNew = stats.data?.total === 0;

  return (
    <>
      <PageHeader
        title={`Welcome${user ? `, ${user.display_name.split(" ")[0]}` : ""}`}
        description="An overview of your research workspace."
        actions={
          <Button asChild>
            <Link href="/research/new">
              <Plus /> New research task
            </Link>
          </Button>
        }
      />

      {stats.isError ? (
        <ErrorState
          className="mb-6"
          message={errorMessage(stats.error)}
          onRetry={() => void stats.refetch()}
        />
      ) : (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Research tasks" value={stats.data?.total} icon={Layers} hint="All tasks you own" />
          <StatCard
            label="Active"
            value={stats.data?.active}
            icon={ActivityIcon}
            hint="Planning, queued, running or paused"
          />
          <StatCard label="Completed" value={stats.data?.completed} icon={CheckCircle2} hint="Finished successfully" />
          <StatCard label="Failed" value={stats.data?.failed} icon={CircleAlert} hint="Stopped with an error" />
        </div>
      )}

      {isNew ? (
        <Card>
          <EmptyState
            icon={Search}
            title="No research yet"
            description={
              <>
                Create a research task by describing what you want to find out. In upcoming releases
                PARE will draft a plan for you to approve, then collect and verify the information
                with sources.
              </>
            }
            action={
              <Button asChild size="sm">
                <Link href="/research/new">
                  <Plus /> Create your first research task
                </Link>
              </Button>
            }
          />
          <div className="grid gap-4 border-t px-6 py-5 text-sm sm:grid-cols-3">
            {[
              ["1. Describe", "Write the objective: what to find and which fields matter."],
              ["2. Approve a plan", "Review queries, sources and limits before anything runs."],
              ["3. Get sourced results", "Every value links back to the evidence it came from."],
            ].map(([title, text]) => (
              <div key={title} className="space-y-1">
                <p className="font-medium">{title}</p>
                <p className="text-muted-foreground">{text}</p>
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
          <Card className="overflow-hidden">
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <FileText className="size-4 text-muted-foreground" aria-hidden /> Recent tasks
              </CardTitle>
              <Link href="/research" className="text-[13px] text-primary hover:underline">
                View all
              </Link>
            </CardHeader>
            <RecentTasks />
          </Card>
          <Card className="h-fit">
            <CardHeader>
              <CardTitle>Recent activity</CardTitle>
            </CardHeader>
            <RecentActivity />
          </Card>
        </div>
      )}
    </>
  );
}
