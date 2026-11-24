"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, queryKeys, type TaskListParams } from "@/lib/api";
import type { TaskInput } from "@/types/api";

export function useTaskList(params: TaskListParams) {
  return useQuery({
    queryKey: queryKeys.taskList(params),
    queryFn: () => api.tasks.list(params),
    placeholderData: keepPreviousData,
  });
}

export function useTask(id: string) {
  return useQuery({ queryKey: queryKeys.task(id), queryFn: () => api.tasks.get(id) });
}

function useInvalidateTasks() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.tasks });
    void qc.invalidateQueries({ queryKey: queryKeys.projects });
  };
}

export function useCreateTask() {
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (input: TaskInput) => api.tasks.create(input),
    onSuccess: invalidate,
  });
}

export function useUpdateTask(id: string) {
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (input: Partial<TaskInput>) => api.tasks.update(id, input),
    onSuccess: invalidate,
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (id: string) => api.tasks.remove(id),
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: queryKeys.task(id) });
      invalidate();
    },
  });
}
