"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";

import { api, queryKeys } from "@/lib/api";
import { ApiError } from "@/lib/api-client";
import type { User } from "@/types/api";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, password: string, displayName: string) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  const me = useQuery({
    queryKey: queryKeys.me,
    queryFn: async () => {
      try {
        return await api.auth.me();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  const loginMutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      api.auth.login(email, password),
  });
  const registerMutation = useMutation({
    mutationFn: (v: { email: string; password: string; displayName: string }) =>
      api.auth.register(v.email, v.password, v.displayName),
  });

  // Drop every cached query except the session itself. queryClient.clear() must not be
  // used here: it detaches the mounted `me` observer from the cache, so the previous user
  // would stay visible after sign-out.
  const resetUserData = useCallback(
    (user: User | null) => {
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== queryKeys.me[0] });
      queryClient.setQueryData(queryKeys.me, user);
    },
    [queryClient],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await loginMutation.mutateAsync({ email, password });
      resetUserData(res.user);
      return res.user;
    },
    [loginMutation, resetUserData],
  );

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      const user = await registerMutation.mutateAsync({ email, password, displayName });
      resetUserData(user);
      return user;
    },
    [registerMutation, resetUserData],
  );

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      resetUserData(null);
    }
  }, [resetUserData]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: me.data ?? null,
      isLoading: me.isPending,
      error: me.error,
      refetch: () => void me.refetch(),
      login,
      register,
      logout,
    }),
    [me, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
