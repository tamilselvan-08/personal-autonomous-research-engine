"use client";

import { ArrowDown, ArrowUp, Crown, Play, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { Skeleton, Spinner } from "@/components/ui/misc";
import {
  usePolicy,
  useRoutes,
  useSetRoute,
  useTestRoute,
  useUpdatePolicy,
} from "@/features/ai-providers/hooks";
import {
  ERROR_CLASS_LABELS,
  outcomeMeta,
  ROLE_META,
  formatMs,
} from "@/features/ai-providers/meta";
import { HealthBadge } from "@/features/ai-providers/provider-card";
import { errorMessage } from "@/lib/api-client";
import { MODEL_ROLES, type AIProvider, type ModelRole, type RoutingPolicy, type RoutingTestResult } from "@/types/api";

interface ChainItem {
  modelId: string;
  label: string;
  provider: string;
  available: boolean;
  reason: string | null;
  health: string;
}

/** Pure helpers so ordering logic is testable. */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}

function ChainEditor({
  role,
  initial,
  providers,
  result,
  setResult,
}: {
  role: ModelRole;
  initial: ChainItem[];
  providers: AIProvider[];
  // Owned by the parent: the editor remounts when health changes after a test, and the
  // result must survive that.
  result: RoutingTestResult | null;
  setResult: (r: RoutingTestResult | null) => void;
}) {
  const setRoute = useSetRoute();
  const testRoute = useTestRoute();
  const [chain, setChain] = useState<ChainItem[]>(initial);
  const dirty = chain.map((c) => c.modelId).join() !== initial.map((c) => c.modelId).join();

  const candidates = providers.flatMap((p) =>
    p.models
      .filter((m) => !chain.some((c) => c.modelId === m.id))
      .map((m) => ({
        modelId: m.id,
        label: m.model_identifier,
        provider: p.display_name,
        available: p.enabled && m.enabled,
        reason: !p.enabled ? "Provider is disabled." : !m.enabled ? "Model is disabled." : null,
        health: p.health_state,
      })),
  );

  function save() {
    setRoute.mutate(
      { role, modelIds: chain.map((c) => c.modelId) },
      {
        onSuccess: () => toast.success(`${ROLE_META[role].label} routing saved`),
        onError: (e) => toast.error(errorMessage(e)),
      },
    );
  }

  return (
    <div className="space-y-4">
      {chain.length ? (
        <ol className="space-y-2" aria-label={`${ROLE_META[role].label} model chain`}>
          {chain.map((item, i) => (
            <li
              key={item.modelId}
              className="flex flex-col gap-2 rounded-md border px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Badge tone={i === 0 ? "accent" : "neutral"}>{i === 0 ? "Primary" : `Fallback ${i}`}</Badge>
                <span className="font-mono text-[13px]">{item.label}</span>
                <span className="text-[13px] text-muted-foreground">· {item.provider}</span>
                {!item.available ? (
                  <Badge tone="warning" title={item.reason ?? undefined}>
                    Skipped: {item.reason}
                  </Badge>
                ) : item.health !== "healthy" && item.health !== "unknown" ? (
                  <HealthBadge state={item.health} />
                ) : null}
              </div>
              <div className="flex shrink-0 gap-1">
                {i > 0 ? (
                  <Button size="icon-sm" variant="ghost" aria-label={`Make ${item.label} primary`} title="Make primary" onClick={() => setChain(moveItem(chain, i, 0))}>
                    <Crown />
                  </Button>
                ) : null}
                <Button size="icon-sm" variant="ghost" aria-label={`Move ${item.label} up`} disabled={i === 0} onClick={() => setChain(moveItem(chain, i, i - 1))}>
                  <ArrowUp />
                </Button>
                <Button size="icon-sm" variant="ghost" aria-label={`Move ${item.label} down`} disabled={i === chain.length - 1} onClick={() => setChain(moveItem(chain, i, i + 1))}>
                  <ArrowDown />
                </Button>
                <Button size="icon-sm" variant="ghost" aria-label={`Remove ${item.label} from chain`} onClick={() => setChain(chain.filter((_, j) => j !== i))}>
                  <X />
                </Button>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">
          {role === "default"
            ? "No primary model yet. Add one below — PARE needs it before it can plan research."
            : "No chain of its own: this role uses the Default chain."}
        </p>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <NativeSelect
          aria-label="Add a model to the chain"
          className="sm:max-w-80"
          value=""
          disabled={!candidates.length || chain.length >= 10}
          onChange={(e) => {
            const pick = candidates.find((c) => c.modelId === e.target.value);
            if (pick) setChain([...chain, pick]);
          }}
        >
          <option value="">
            {candidates.length ? (chain.length ? "Add a fallback model…" : "Choose the primary model…") : "No other models configured"}
          </option>
          {candidates.map((c) => (
            <option key={c.modelId} value={c.modelId} disabled={!c.available}>
              {c.provider} / {c.label}
              {!c.available ? " (disabled)" : ""}
            </option>
          ))}
        </NativeSelect>
        <div className="flex gap-2 sm:ml-auto">
          {dirty ? (
            <Button variant="ghost" size="sm" onClick={() => setChain(initial)}>
              Discard
            </Button>
          ) : null}
          <Button size="sm" onClick={save} disabled={!dirty || setRoute.isPending}>
            {setRoute.isPending ? "Saving…" : "Save routing"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={dirty || testRoute.isPending}
            title={dirty ? "Save first" : "Send a 5-token prompt through the chain"}
            onClick={() =>
              testRoute.mutate(role, { onSuccess: setResult, onError: (e) => toast.error(errorMessage(e)) })
            }
          >
            {testRoute.isPending ? <Spinner /> : <Play />} Test routing
          </Button>
        </div>
      </div>

      {result ? <RoutingResult result={result} /> : null}
    </div>
  );
}

function RoutingResult({ result }: { result: RoutingTestResult }) {
  return (
    <div role="status" className="space-y-2 rounded-md border bg-muted/40 px-3 py-3 text-sm">
      <p className="font-medium">
        {result.ok
          ? `Answered by ${result.provider_name} / ${result.model_identifier} in ${formatMs(result.latency_ms)}${result.used_fallback ? " (after fallback)" : ""}`
          : result.message}
      </p>
      {result.attempts.length ? (
        <ol className="space-y-1 text-[13px]">
          {result.attempts.map((a, i) => {
            const meta = outcomeMeta(a.outcome);
            return (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <Badge tone={meta.tone}>{meta.label}</Badge>
                <span className="font-mono">
                  {a.provider_name} / {a.model_identifier}
                </span>
                {a.error_class ? (
                  <span className="text-muted-foreground">
                    {ERROR_CLASS_LABELS[a.error_class] ?? a.error_class}
                    {a.http_status ? ` (HTTP ${a.http_status})` : ""}
                  </span>
                ) : null}
                {a.outcome === "skipped" && a.message ? (
                  <span className="text-muted-foreground">{a.message}</span>
                ) : null}
                {a.latency_ms !== null ? <span className="text-muted-foreground">{formatMs(a.latency_ms)}</span> : null}
              </li>
            );
          })}
        </ol>
      ) : null}
    </div>
  );
}

function PolicyEditor({ policy }: { policy: RoutingPolicy }) {
  const update = useUpdatePolicy();
  const [draft, setDraft] = useState(policy);
  const dirty = JSON.stringify(draft) !== JSON.stringify(policy);
  return (
    <div className="space-y-3 border-t pt-4">
      <div>
        <p className="text-sm font-medium">Retries and fallback</p>
        <p className="text-[13px] text-muted-foreground">
          Timeouts, connection errors and temporary provider errors are retried with backoff, then
          the next model is tried. Rejected keys, unknown models and invalid requests are never
          retried or passed on — they are shown to you instead.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex items-center gap-2 text-sm">
          Retries per model
          <Input
            type="number"
            min={0}
            max={5}
            className="w-20"
            value={draft.max_retries}
            onChange={(e) => setDraft({ ...draft, max_retries: Math.max(0, Math.min(5, Number(e.target.value))) })}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          Wait at most (s) for Retry-After
          <Input
            type="number"
            min={0}
            max={120}
            className="w-20"
            value={draft.max_retry_after_seconds}
            onChange={(e) =>
              setDraft({ ...draft, max_retry_after_seconds: Math.max(0, Math.min(120, Number(e.target.value))) })
            }
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.fallback_on_rate_limit}
            onChange={(e) => setDraft({ ...draft, fallback_on_rate_limit: e.target.checked })}
          />
          Fall back when rate-limited
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.fallback_on_quota_exhausted}
            onChange={(e) => setDraft({ ...draft, fallback_on_quota_exhausted: e.target.checked })}
          />
          Fall back when an account is out of credit
        </label>
      </div>
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="outline"
          disabled={!dirty || update.isPending}
          onClick={() =>
            update.mutate(draft, {
              onSuccess: () => toast.success("Policy saved"),
              onError: (e) => toast.error(errorMessage(e)),
            })
          }
        >
          Save policy
        </Button>
      </div>
    </div>
  );
}

export function RoutingCard({ providers }: { providers: AIProvider[] }) {
  const routes = useRoutes();
  const policy = usePolicy();
  const [role, setRole] = useState<ModelRole>("default");
  const [results, setResults] = useState<Partial<Record<ModelRole, RoutingTestResult>>>({});
  const current = routes.data?.roles.find((r) => r.role === role);
  const initial: ChainItem[] =
    current?.entries.map((e) => ({
      modelId: e.model_id,
      label: e.model_identifier,
      provider: e.provider_name,
      available: e.available,
      reason: e.unavailable_reason,
      health: e.health_state,
    })) ?? [];

  return (
    <Card>
      <CardHeader className="sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle>Routing</CardTitle>
          <CardDescription>
            The primary model answers first; fallbacks are tried in order when it fails temporarily.
          </CardDescription>
        </div>
        <NativeSelect
          aria-label="Role"
          className="sm:max-w-56"
          value={role}
          onChange={(e) => setRole(e.target.value as ModelRole)}
        >
          {MODEL_ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_META[r].label}
            </option>
          ))}
        </NativeSelect>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-[13px] text-muted-foreground">{ROLE_META[role].hint}</p>
        {routes.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : routes.isError ? (
          <p className="text-sm text-destructive">{errorMessage(routes.error)}</p>
        ) : (
          <ChainEditor
            // Re-seed the editor when the role or the saved chain changes.
            key={`${role}:${initial.map((i) => `${i.modelId}${i.available}${i.health}`).join()}`}
            role={role}
            initial={initial}
            providers={providers}
            result={results[role] ?? null}
            setResult={(r) => setResults((prev) => ({ ...prev, [role]: r ?? undefined }))}
          />
        )}
        {policy.data ? <PolicyEditor key={JSON.stringify(policy.data)} policy={policy.data} /> : null}
      </CardContent>
    </Card>
  );
}
