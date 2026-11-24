import { apiRequest } from "@/lib/api-client";
import type {
  Activity,
  AIModel,
  AIProvider,
  AppSettings,
  ConnectionTestResult,
  DiscoveredModels,
  ModelInput,
  ModelRole,
  ProviderCreateInput,
  ProviderHealth,
  ProviderTypes,
  ProviderUpdateInput,
  RoleRoute,
  RoutingPolicy,
  RoutingTestResult,
  UsageGroupBy,
  UsageRecord,
  UsageSummary,
  LoginResponse,
  Page,
  Project,
  ProjectInput,
  Readiness,
  ResearchTask,
  TaskInput,
  TaskSort,
  TaskStats,
  TaskStatus,
  User,
} from "@/types/api";

export interface TaskListParams {
  page?: number;
  pageSize?: number;
  q?: string;
  status?: TaskStatus[];
  projectId?: string;
  sort?: TaskSort;
}

export const api = {
  auth: {
    me: () => apiRequest<User>("/auth/me"),
    login: (email: string, password: string) =>
      apiRequest<LoginResponse>("/auth/login", { method: "POST", body: { email, password } }),
    register: (email: string, password: string, display_name: string) =>
      apiRequest<User>("/auth/register", {
        method: "POST",
        body: { email, password, display_name },
      }),
    logout: () => apiRequest<void>("/auth/logout", { method: "POST" }),
  },
  tasks: {
    list: (p: TaskListParams = {}) =>
      apiRequest<Page<ResearchTask>>("/tasks", {
        query: {
          page: p.page,
          page_size: p.pageSize,
          q: p.q,
          status: p.status,
          project_id: p.projectId,
          sort: p.sort,
        },
      }),
    get: (id: string) => apiRequest<ResearchTask>(`/tasks/${id}`),
    create: (input: TaskInput) =>
      apiRequest<ResearchTask>("/tasks", { method: "POST", body: input }),
    update: (id: string, input: Partial<TaskInput>) =>
      apiRequest<ResearchTask>(`/tasks/${id}`, { method: "PATCH", body: input }),
    remove: (id: string) => apiRequest<void>(`/tasks/${id}`, { method: "DELETE" }),
    stats: () => apiRequest<TaskStats>("/tasks/stats"),
    recentActivity: (limit = 8) =>
      apiRequest<Activity[]>("/tasks/recent-activity", { query: { limit } }),
  },
  projects: {
    list: (p: { page?: number; pageSize?: number; q?: string } = {}) =>
      apiRequest<Page<Project>>("/projects", {
        query: { page: p.page, page_size: p.pageSize, q: p.q },
      }),
    get: (id: string) => apiRequest<Project>(`/projects/${id}`),
    create: (input: ProjectInput) =>
      apiRequest<Project>("/projects", { method: "POST", body: input }),
    update: (id: string, input: Partial<ProjectInput>) =>
      apiRequest<Project>(`/projects/${id}`, { method: "PATCH", body: input }),
    remove: (id: string, detachTasks = false) =>
      apiRequest<void>(`/projects/${id}`, {
        method: "DELETE",
        query: { detach_tasks: detachTasks || undefined },
      }),
  },
  ai: {
    types: () => apiRequest<ProviderTypes>("/providers/types"),
    providers: () => apiRequest<AIProvider[]>("/providers"),
    createProvider: (input: ProviderCreateInput) =>
      apiRequest<AIProvider>("/providers", { method: "POST", body: input }),
    updateProvider: (id: string, input: ProviderUpdateInput) =>
      apiRequest<AIProvider>(`/providers/${id}`, { method: "PATCH", body: input }),
    deleteProvider: (id: string, force = false) =>
      apiRequest<void>(`/providers/${id}`, {
        method: "DELETE",
        query: { force: force || undefined },
      }),
    replaceKey: (id: string, apiKey: string) =>
      apiRequest<AIProvider>(`/providers/${id}/key`, { method: "PUT", body: { api_key: apiKey } }),
    removeKey: (id: string) => apiRequest<AIProvider>(`/providers/${id}/key`, { method: "DELETE" }),
    testConnection: (id: string, modelId?: string) =>
      apiRequest<ConnectionTestResult>(`/providers/${id}/test`, {
        method: "POST",
        body: modelId ? { model_id: modelId } : {},
      }),
    availableModels: (id: string) =>
      apiRequest<DiscoveredModels>(`/providers/${id}/available-models`),
    addModel: (providerId: string, input: ModelInput) =>
      apiRequest<AIModel>(`/providers/${providerId}/models`, { method: "POST", body: input }),
    updateModel: (id: string, input: Partial<ModelInput>) =>
      apiRequest<AIModel>(`/models/${id}`, { method: "PATCH", body: input }),
    deleteModel: (id: string, force = false) =>
      apiRequest<void>(`/models/${id}`, { method: "DELETE", query: { force: force || undefined } }),
    routes: () => apiRequest<{ roles: RoleRoute[] }>("/model-routes"),
    setRoute: (role: ModelRole, modelIds: string[]) =>
      apiRequest<{ roles: RoleRoute[] }>(`/model-routes/${role}`, {
        method: "PUT",
        body: { model_ids: modelIds },
      }),
    testRoute: (role: ModelRole) =>
      apiRequest<RoutingTestResult>(`/model-routes/${role}/test`, { method: "POST" }),
    policy: () => apiRequest<RoutingPolicy>("/routing-policy"),
    updatePolicy: (input: Partial<RoutingPolicy>) =>
      apiRequest<RoutingPolicy>("/routing-policy", { method: "PUT", body: input }),
    health: () =>
      apiRequest<{ window_hours: number; providers: ProviderHealth[] }>("/providers/health"),
    usage: (groupBy: UsageGroupBy = "provider") =>
      apiRequest<UsageSummary>("/usage", { query: { group_by: groupBy } }),
    usageRecords: (pageSize = 20) =>
      apiRequest<Page<UsageRecord>>("/usage/records", { query: { page_size: pageSize } }),
  },
  system: {
    ready: () => apiRequest<Readiness>("/health/ready"),
    settings: () => apiRequest<AppSettings>("/settings"),
  },
};

export const queryKeys = {
  me: ["me"] as const,
  tasks: ["tasks"] as const,
  taskList: (p: TaskListParams) => ["tasks", "list", p] as const,
  task: (id: string) => ["tasks", "detail", id] as const,
  taskStats: ["tasks", "stats"] as const,
  activity: ["tasks", "activity"] as const,
  projects: ["projects"] as const,
  projectList: (p: object) => ["projects", "list", p] as const,
  project: (id: string) => ["projects", "detail", id] as const,
  ai: ["ai"] as const,
  aiTypes: ["ai", "types"] as const,
  aiProviders: ["ai", "providers"] as const,
  aiRoutes: ["ai", "routes"] as const,
  aiPolicy: ["ai", "policy"] as const,
  aiHealth: ["ai", "health"] as const,
  aiUsage: (groupBy: string) => ["ai", "usage", groupBy] as const,
  aiUsageRecords: ["ai", "usage-records"] as const,
  ready: ["system", "ready"] as const,
  settings: ["system", "settings"] as const,
};
