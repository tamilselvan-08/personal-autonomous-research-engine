"use client";

import { useQuery } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";

import { api, queryKeys } from "@/lib/api";
import { errorMessage } from "@/lib/api-client";

/** Polls readiness and shows a banner only when the backend or database is down. */
export function BackendStatusBanner() {
  const ready = useQuery({
    queryKey: queryKeys.ready,
    queryFn: api.system.ready,
    refetchInterval: 15_000,
    retry: false,
  });

  let message: string | null = null;
  if (ready.isError) message = errorMessage(ready.error);
  else if (ready.data?.status === "degraded") {
    message = "The backend is running but the database is unavailable. Changes cannot be saved.";
  }
  if (!message) return null;

  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive lg:px-8"
    >
      <WifiOff className="size-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}
