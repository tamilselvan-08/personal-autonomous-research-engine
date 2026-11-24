"use client";

import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { DeleteTaskDialog } from "@/features/tasks/delete-task-dialog";
import { StatusBadge } from "@/features/tasks/status-badge";
import { formatDateTime, formatRelative } from "@/lib/utils";
import type { ResearchTask } from "@/types/api";

export function TaskTable({ tasks, showProject = true }: { tasks: ResearchTask[]; showProject?: boolean }) {
  const router = useRouter();
  const [toDelete, setToDelete] = useState<ResearchTask | null>(null);

  return (
    <>
      <Table>
        <THead>
          <TR>
            <TH>Task</TH>
            <TH className="w-44">Status</TH>
            {showProject ? <TH className="hidden w-44 md:table-cell">Project</TH> : null}
            <TH className="hidden w-36 sm:table-cell">Updated</TH>
            <TH className="w-12">
              <span className="sr-only">Actions</span>
            </TH>
          </TR>
        </THead>
        <TBody>
          {tasks.map((task) => (
            <TR key={task.id} className="hover:bg-muted/40">
              <TD className="max-w-0">
                <Link
                  href={`/research/${task.id}`}
                  className="block truncate font-medium hover:underline"
                >
                  {task.title}
                </Link>
                <p className="truncate text-[13px] text-muted-foreground">{task.objective}</p>
              </TD>
              <TD>
                <StatusBadge status={task.status} />
              </TD>
              {showProject ? (
                <TD className="hidden text-muted-foreground md:table-cell">
                  {task.project ? (
                    <Link href={`/projects/${task.project.id}`} className="hover:underline">
                      {task.project.name}
                    </Link>
                  ) : (
                    "—"
                  )}
                </TD>
              ) : null}
              <TD className="hidden text-muted-foreground sm:table-cell">
                <time dateTime={task.updated_at} title={formatDateTime(task.updated_at)}>
                  {formatRelative(task.updated_at)}
                </time>
              </TD>
              <TD>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${task.title}`}>
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      disabled={!task.is_editable}
                      onSelect={() => router.push(`/research/${task.id}/edit`)}
                    >
                      <Pencil /> Edit
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={!task.is_deletable}
                      className="text-destructive data-[highlighted]:text-destructive"
                      onSelect={() => setToDelete(task)}
                    >
                      <Trash2 /> Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <DeleteTaskDialog task={toDelete} onOpenChange={(open) => !open && setToDelete(null)} />
    </>
  );
}
