"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { useHealth, useUsage, useUsageRecords } from "@/features/ai-providers/hooks";
import {
  ERROR_CLASS_LABELS,
  outcomeMeta,
  PURPOSE_LABELS,
  formatCost,
  formatMs,
  formatPercent,
} from "@/features/ai-providers/meta";
import { HealthBadge } from "@/features/ai-providers/provider-card";
import { formatRelative } from "@/lib/utils";
import type { UsageGroupBy } from "@/types/api";

export function HealthCard() {
  const health = useHealth();
  const rows = health.data?.providers ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Health</CardTitle>
        <CardDescription>Calls in the last {health.data?.window_hours ?? 24} hours, including tests.</CardDescription>
      </CardHeader>
      <CardContent className="px-0 py-0">
        {health.isPending ? (
          <Skeleton className="m-5 h-20" />
        ) : rows.length === 0 ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">No providers yet.</p>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Provider</TH>
                <TH>Status</TH>
                <TH className="text-right">Calls</TH>
                <TH className="text-right">Success</TH>
                <TH className="text-right">p50</TH>
                <TH className="text-right">p95</TH>
                <TH>Last error</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((r) => (
                <TR key={r.provider_id}>
                  <TD className="font-medium">{r.display_name}</TD>
                  <TD>
                    <HealthBadge state={r.health_state} />
                  </TD>
                  <TD className="text-right tabular-nums">{r.calls}</TD>
                  <TD className="text-right tabular-nums">{formatPercent(r.success_rate)}</TD>
                  <TD className="text-right tabular-nums">{formatMs(r.p50_latency_ms)}</TD>
                  <TD className="text-right tabular-nums">{formatMs(r.p95_latency_ms)}</TD>
                  <TD className="max-w-64 truncate text-[13px] text-muted-foreground" title={r.last_error_message ?? undefined}>
                    {r.last_error_class
                      ? `${ERROR_CLASS_LABELS[r.last_error_class] ?? r.last_error_class}${r.last_error_at ? `, ${formatRelative(r.last_error_at)}` : ""}`
                      : "—"}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

const GROUPS: { value: UsageGroupBy; label: string }[] = [
  { value: "provider", label: "By provider" },
  { value: "model", label: "By model" },
  { value: "day", label: "By day" },
  { value: "purpose", label: "By purpose" },
];

export function UsageCard() {
  const [groupBy, setGroupBy] = useState<UsageGroupBy>("provider");
  const usage = useUsage(groupBy);
  const records = useUsageRecords();
  const label = (key: string, text: string) =>
    groupBy === "purpose" ? (PURPOSE_LABELS[key] ?? text) : text;

  return (
    <Card>
      <CardHeader className="sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle>Usage</CardTitle>
          <CardDescription>
            Last 7 days. Cost is estimated only for models with prices set; prompts and replies are
            never stored.
          </CardDescription>
        </div>
        <NativeSelect
          aria-label="Group usage"
          className="sm:max-w-44"
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as UsageGroupBy)}
        >
          {GROUPS.map((g) => (
            <option key={g.value} value={g.value}>
              {g.label}
            </option>
          ))}
        </NativeSelect>
      </CardHeader>
      <CardContent className="space-y-6 px-0 py-0">
        {usage.isPending ? (
          <Skeleton className="m-5 h-20" />
        ) : !usage.data || usage.data.totals.calls === 0 ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">No AI calls yet.</p>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>{GROUPS.find((g) => g.value === groupBy)?.label.replace("By ", "")}</TH>
                <TH className="text-right">Calls</TH>
                <TH className="text-right">Failed</TH>
                <TH className="text-right">Tokens in / out</TH>
                <TH className="text-right">Avg latency</TH>
                <TH className="text-right">Est. cost</TH>
              </TR>
            </THead>
            <TBody>
              {[...usage.data.rows, usage.data.totals].map((r) => (
                <TR key={r.key} className={r.key === "total" ? "font-medium" : undefined}>
                  <TD>{label(r.key, r.label)}</TD>
                  <TD className="text-right tabular-nums">{r.calls}</TD>
                  <TD className="text-right tabular-nums">{r.failures}</TD>
                  <TD className="text-right tabular-nums">
                    {r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}
                  </TD>
                  <TD className="text-right tabular-nums">{formatMs(r.avg_latency_ms)}</TD>
                  <TD className="text-right tabular-nums">{formatCost(r.est_cost_usd)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}

        {records.data && records.data.items.length ? (
          <div className="border-t">
            <p className="px-5 pt-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Recent calls
            </p>
            <Table>
              <THead>
                <TR>
                  <TH>When</TH>
                  <TH>Provider / model</TH>
                  <TH>Purpose</TH>
                  <TH>Outcome</TH>
                  <TH className="text-right">Latency</TH>
                </TR>
              </THead>
              <TBody>
                {records.data.items.map((r) => {
                  const meta = outcomeMeta(r.outcome);
                  return (
                    <TR key={r.id}>
                      <TD className="whitespace-nowrap text-[13px] text-muted-foreground">
                        {formatRelative(r.created_at)}
                      </TD>
                      <TD className="font-mono text-[13px]">
                        {r.provider_name} / {r.model_identifier}
                      </TD>
                      <TD className="text-[13px]">{PURPOSE_LABELS[r.purpose] ?? r.purpose}</TD>
                      <TD>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge tone={meta.tone}>{meta.label}</Badge>
                          {r.error_class ? (
                            <span className="text-[12px] text-muted-foreground">
                              {ERROR_CLASS_LABELS[r.error_class] ?? r.error_class}
                            </span>
                          ) : null}
                        </div>
                      </TD>
                      <TD className="text-right tabular-nums">{formatMs(r.latency_ms)}</TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
