"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, queryKeys } from "@/lib/api";
import type { ProjectInput } from "@/types/api";

export function useProjectList(params: { page?: number; pageSize?: number; q?: string } = {}) {
  return useQuery({
    queryKey: queryKeys.projectList(params),
    queryFn: () => api.projects.list(params),
  });
}

/** All projects for pickers (the API caps a page at 100). */
export function useProjectOptions() {
  return useProjectList({ page: 1, pageSize: 100 });
}

export function useProject(id: string) {
  return useQuery({ queryKey: queryKeys.project(id), queryFn: () => api.projects.get(id) });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.projects });
    void qc.invalidateQueries({ queryKey: queryKeys.tasks });
  };
}

export function useSaveProject(id?: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (input: ProjectInput) =>
      id ? api.projects.update(id, input) : api.projects.create(input),
    onSuccess: invalidate,
  });
}

export function useDeleteProject() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, detachTasks }: { id: string; detachTasks: boolean }) =>
      api.projects.remove(id, detachTasks),
    onSuccess: invalidate,
  });
}
