"use client";

import { FolderKanban, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { Pagination } from "@/components/ui/pagination";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { useProjectList } from "@/features/projects/hooks";
import { DeleteProjectDialog, ProjectDialog } from "@/features/projects/project-dialogs";
import { errorMessage } from "@/lib/api-client";
import { formatRelative, pluralize } from "@/lib/utils";
import type { Project } from "@/types/api";

const PAGE_SIZE = 20;

export default function ProjectsPage() {
  const [page, setPage] = useState(1);
  const list = useProjectList({ page, pageSize: PAGE_SIZE });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  return (
    <>
      <PageHeader
        title="Projects"
        description="Group related research tasks, for example by client or topic."
        actions={
          <Button onClick={openCreate}>
            <Plus /> New project
          </Button>
        }
      />
      <Card className="overflow-hidden">
        {list.isPending ? (
          <div className="space-y-3 p-4" aria-busy>
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : list.isError ? (
          <div className="p-4">
            <ErrorState message={errorMessage(list.error)} onRetry={() => void list.refetch()} />
          </div>
        ) : list.data.items.length === 0 ? (
          <EmptyState
            icon={FolderKanban}
            title="No projects yet"
            description="Projects are optional. Create one to keep related research tasks together."
            action={
              <Button size="sm" onClick={openCreate}>
                <Plus /> Create a project
              </Button>
            }
          />
        ) : (
          <>
            <Table>
              <THead>
                <TR>
                  <TH>Project</TH>
                  <TH className="w-32">Tasks</TH>
                  <TH className="hidden w-36 sm:table-cell">Updated</TH>
                  <TH className="w-12">
                    <span className="sr-only">Actions</span>
                  </TH>
                </TR>
              </THead>
              <TBody>
                {list.data.items.map((p) => (
                  <TR key={p.id} className="hover:bg-muted/40">
                    <TD className="max-w-0">
                      <Link href={`/projects/${p.id}`} className="block truncate font-medium hover:underline">
                        {p.name}
                      </Link>
                      {p.description ? (
                        <p className="truncate text-[13px] text-muted-foreground">{p.description}</p>
                      ) : null}
                    </TD>
                    <TD className="text-muted-foreground">{pluralize(p.task_count, "task")}</TD>
                    <TD className="hidden text-muted-foreground sm:table-cell">
                      {formatRelative(p.updated_at)}
                    </TD>
                    <TD>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${p.name}`}>
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onSelect={() => {
                              setEditing(p);
                              setDialogOpen(true);
                            }}
                          >
                            <Pencil /> Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive data-[highlighted]:text-destructive"
                            onSelect={() => setDeleting(p)}
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

      <ProjectDialog open={dialogOpen} onOpenChange={setDialogOpen} project={editing} />
      <DeleteProjectDialog project={deleting} onOpenChange={(o) => !o && setDeleting(null)} />
    </>
  );
}
