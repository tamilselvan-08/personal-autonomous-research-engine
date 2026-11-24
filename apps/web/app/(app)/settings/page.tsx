"use client";

import { useQuery } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { useEffect, useState, type ReactNode } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/input";
import { ErrorState, Skeleton } from "@/components/ui/misc";
import { useAuth } from "@/hooks/use-auth";
import { api, queryKeys } from "@/lib/api";
import { API_BASE_URL, errorMessage } from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[12rem_1fr] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function StatusPill({ ok, okLabel, badLabel }: { ok: boolean; okLabel: string; badLabel: string }) {
  return <Badge tone={ok ? "success" : "danger"}>{ok ? okLabel : badLabel}</Badge>;
}

function ThemeSetting() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);
  return (
    <NativeSelect
      aria-label="Theme"
      className="max-w-48"
      value={mounted ? theme : "system"}
      onChange={(e) => setTheme(e.target.value)}
    >
      <option value="system">System</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </NativeSelect>
  );
}

const FEATURE_LABELS: Record<string, string> = {
  ai_providers: "AI provider management",
  research_planning: "Research planning",
  research_execution: "Autonomous execution",
  browser_manager: "Browser profile manager",
  scheduling: "Scheduling",
};

export default function SettingsPage() {
  const { user } = useAuth();
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: api.system.settings,
    refetchInterval: 30_000,
  });
  const ready = useQuery({
    queryKey: queryKeys.ready,
    queryFn: api.system.ready,
    refetchInterval: 15_000,
    retry: false,
  });
  const backendReachable = !ready.isError && ready.data !== undefined;
  const dbOk = ready.data?.checks.database?.status === "ok";

  return (
    <>
      <PageHeader title="Settings" description="Application preferences and system status." />
      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Preferences</CardTitle>
            <CardDescription>Stored in this browser.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="divide-y">
              <Row label="Theme">
                <ThemeSetting />
              </Row>
              <Row label="Signed in as">
                {user ? `${user.display_name} (${user.email})` : "—"}
              </Row>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System status</CardTitle>
            <CardDescription>Checked every 15 seconds.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="divide-y">
              <Row label="Backend API">
                {ready.isPending ? (
                  <Skeleton className="h-5 w-24" />
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill ok={backendReachable} okLabel="Connected" badLabel="Unreachable" />
                    <span className="font-mono text-xs text-muted-foreground">{API_BASE_URL}</span>
                  </div>
                )}
              </Row>
              <Row label="Database">
                {ready.isPending ? (
                  <Skeleton className="h-5 w-24" />
                ) : !backendReachable ? (
                  <span className="text-muted-foreground">Unknown (backend unreachable)</span>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill ok={dbOk} okLabel="Healthy" badLabel="Unavailable" />
                    {ready.data?.checks.database?.latency_ms != null ? (
                      <span className="text-xs text-muted-foreground">
                        {ready.data.checks.database.latency_ms} ms
                      </span>
                    ) : null}
                  </div>
                )}
              </Row>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System information</CardTitle>
          </CardHeader>
          <CardContent>
            {settings.isPending ? (
              <Skeleton className="h-40 w-full" />
            ) : settings.isError ? (
              <ErrorState message={errorMessage(settings.error)} onRetry={() => void settings.refetch()} />
            ) : (
              <dl className="divide-y">
                <Row label="Application">
                  {settings.data.app_name} {settings.data.version}
                </Row>
                <Row label="Environment">{settings.data.environment}</Row>
                <Row label="Database version">{settings.data.database.version ?? "—"}</Row>
                <Row label="Schema revision">
                  <span className="font-mono text-xs">{settings.data.database.migration_revision ?? "—"}</span>
                </Row>
                <Row label="Python">{settings.data.python_version}</Row>
                <Row label="Server time">{formatDateTime(settings.data.server_time)}</Row>
                <Row label="Registration">
                  {settings.data.registration_enabled ? "Open to new local accounts" : "Disabled"}
                </Row>
                <Row label="Features">
                  <ul className="flex flex-wrap gap-1.5">
                    {Object.entries(settings.data.features).map(([key, enabled]) => (
                      <li key={key}>
                        <Badge tone={enabled ? "success" : "neutral"}>
                          {FEATURE_LABELS[key] ?? key}: {enabled ? "available" : "coming soon"}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </Row>
              </dl>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
