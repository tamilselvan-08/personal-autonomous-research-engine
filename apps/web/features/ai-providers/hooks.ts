"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, queryKeys } from "@/lib/api";
import type {
  ModelInput,
  ModelRole,
  ProviderCreateInput,
  ProviderUpdateInput,
  RoutingPolicy,
  UsageGroupBy,
} from "@/types/api";

export function useProviderTypes() {
  return useQuery({ queryKey: queryKeys.aiTypes, queryFn: api.ai.types, staleTime: 5 * 60_000 });
}

export function useProviders() {
  return useQuery({ queryKey: queryKeys.aiProviders, queryFn: api.ai.providers });
}

export function useRoutes() {
  return useQuery({ queryKey: queryKeys.aiRoutes, queryFn: api.ai.routes });
}

export function usePolicy() {
  return useQuery({ queryKey: queryKeys.aiPolicy, queryFn: api.ai.policy });
}

export function useHealth() {
  return useQuery({ queryKey: queryKeys.aiHealth, queryFn: api.ai.health, refetchInterval: 30_000 });
}

export function useUsage(groupBy: UsageGroupBy) {
  return useQuery({ queryKey: queryKeys.aiUsage(groupBy), queryFn: () => api.ai.usage(groupBy) });
}

export function useUsageRecords() {
  return useQuery({ queryKey: queryKeys.aiUsageRecords, queryFn: () => api.ai.usageRecords(15) });
}

/** Everything on the page derives from providers, routes, health and usage. */
function useInvalidateAI() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: queryKeys.ai });
}

export function useCreateProvider() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: (input: ProviderCreateInput) => api.ai.createProvider(input),
    onSuccess: invalidate,
  });
}

export function useUpdateProvider() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ProviderUpdateInput }) =>
      api.ai.updateProvider(id, input),
    onSuccess: invalidate,
  });
}

export function useDeleteProvider() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ id, force }: { id: string; force: boolean }) => api.ai.deleteProvider(id, force),
    onSuccess: invalidate,
  });
}

export function useReplaceKey() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ id, apiKey }: { id: string; apiKey: string }) => api.ai.replaceKey(id, apiKey),
    onSuccess: invalidate,
  });
}

export function useRemoveKey() {
  const invalidate = useInvalidateAI();
  return useMutation({ mutationFn: (id: string) => api.ai.removeKey(id), onSuccess: invalidate });
}

export function useTestConnection() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ id, modelId }: { id: string; modelId?: string }) =>
      api.ai.testConnection(id, modelId),
    onSettled: invalidate,
  });
}

export function useAddModel() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ providerId, input }: { providerId: string; input: ModelInput }) =>
      api.ai.addModel(providerId, input),
    onSuccess: invalidate,
  });
}

export function useUpdateModel() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<ModelInput> }) =>
      api.ai.updateModel(id, input),
    onSuccess: invalidate,
  });
}

export function useDeleteModel() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ id, force }: { id: string; force: boolean }) => api.ai.deleteModel(id, force),
    onSuccess: invalidate,
  });
}

export function useSetRoute() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ role, modelIds }: { role: ModelRole; modelIds: string[] }) =>
      api.ai.setRoute(role, modelIds),
    onSuccess: invalidate,
  });
}

export function useTestRoute() {
  const invalidate = useInvalidateAI();
  return useMutation({ mutationFn: (role: ModelRole) => api.ai.testRoute(role), onSettled: invalidate });
}

export function useUpdatePolicy() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: (input: Partial<RoutingPolicy>) => api.ai.updatePolicy(input),
    onSuccess: invalidate,
  });
}
