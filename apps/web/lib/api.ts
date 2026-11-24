import { apiRequest } from "@/lib/api-client";
import type {
  Activity,
  AppSettings,
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
  ready: ["system", "ready"] as const,
  settings: ["system", "settings"] as const,
};
