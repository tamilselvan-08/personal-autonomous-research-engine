"use client";

import {
  CheckCircle2,
  KeyRound,
  MoreHorizontal,
  Pencil,
  Plug,
  Plus,
  Power,
  Search,
  Trash2,
  XCircle,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input, NativeSelect } from "@/components/ui/input";
import { Spinner } from "@/components/ui/misc";
import { MODEL_ID_PATTERN } from "@/features/ai-providers/add-provider-dialog";
import {
  useAddModel,
  useTestConnection,
  useUpdateModel,
  useUpdateProvider,
} from "@/features/ai-providers/hooks";
import { ERROR_CLASS_LABELS, ROLE_META, formatMs, healthMeta } from "@/features/ai-providers/meta";
import { api } from "@/lib/api";
import { ApiError, errorMessage } from "@/lib/api-client";
import { formatRelative } from "@/lib/utils";
import type { AIModel, AIProvider, ConnectionTestResult, DiscoveredModel } from "@/types/api";

export interface ProviderActions {
  onEdit: (p: AIProvider) => void;
  onReplaceKey: (p: AIProvider) => void;
  onRemoveKey: (p: AIProvider) => void;
  onDelete: (p: AIProvider) => void;
  onDeleteModel: (m: AIModel) => void;
}

export function HealthBadge({ state }: { state: string }) {
  const meta = healthMeta(state);
  return (
    <Badge tone={meta.tone} title={meta.hint}>
      {meta.label}
    </Badge>
  );
}

function TestResult({ result }: { result: ConnectionTestResult }) {
  return (
    <div
      role="status"
      className={
        result.ok
          ? "flex items-start gap-2 rounded-md border border-success/30 bg-success/5 px-3 py-2 text-sm"
          : "flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm"
      }
    >
      {result.ok ? (
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
      ) : (
        <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
      )}
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">
          {result.ok
            ? `Connected — ${result.model_identifier} answered in ${formatMs(result.latency_ms)}`
            : `${ERROR_CLASS_LABELS[result.error_class ?? "unknown"] ?? "Failed"}${result.http_status ? ` (HTTP ${result.http_status})` : ""}`}
        </p>
        {!result.ok ? (
          <>
            {result.error_hint ? <p>{result.error_hint}</p> : null}
            <p className="break-words text-[13px] text-muted-foreground">{result.message}</p>
          </>
        ) : null}
      </div>
    </div>
  );
}

function AddModelForm({ provider }: { provider: AIProvider }) {
  const add = useAddModel();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredModel[] | null>(null);
  const [browsing, setBrowsing] = useState(false);

  async function submit(identifier: string) {
    setError(null);
    const id = identifier.trim();
    if (!MODEL_ID_PATTERN.test(id) || id.includes("..")) {
      setError("Use the provider's model ID exactly (no spaces).");
      return;
    }
    try {
      await add.mutateAsync({ providerId: provider.id, input: { model_identifier: id } });
      setValue("");
      setDiscovered((d) => d?.map((m) => (m.id === id ? { ...m, configured: true } : m)) ?? null);
      toast.success(`Added ${id}`);
    } catch (e) {
      setError(e instanceof ApiError ? (e.fieldMessages().model_identifier ?? e.message) : errorMessage(e));
    }
  }

  async function browse() {
    setBrowsing(true);
    setError(null);
    try {
      const result = await api.ai.availableModels(provider.id);
      if (result.ok) setDiscovered(result.models);
      else setError(result.message ?? "Could not list models.");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBrowsing(false);
    }
  }

  return (
    <div className="space-y-2">
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void submit(value);
        }}
      >
        <Input
          aria-label={`Add a model to ${provider.display_name}`}
          placeholder="Model ID"
          value={value}
          spellCheck={false}
          maxLength={200}
          onChange={(e) => setValue(e.target.value)}
          className="sm:max-w-64"
        />
        <div className="flex gap-2">
          <Button type="submit" size="sm" variant="outline" disabled={add.isPending || !value.trim()}>
            <Plus /> Add model
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => void browse()}
            disabled={browsing || (!provider.has_key && provider.provider_type !== "openai_compatible")}
            title="Ask the provider which models this key can use"
          >
            {browsing ? <Spinner /> : <Search />} Browse models
          </Button>
        </div>
      </form>
      {discovered ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <NativeSelect
            aria-label="Available models"
            className="sm:max-w-80"
            defaultValue=""
            onChange={(e) => e.target.value && void submit(e.target.value)}
          >
            <option value="" disabled>
              {discovered.length} models available — choose one to add
            </option>
            {discovered.map((m) => (
              <option key={m.id} value={m.id} disabled={m.configured}>
                {m.id}
                {m.configured ? " (added)" : ""}
              </option>
            ))}
          </NativeSelect>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function ModelRow({
  provider,
  model,
  onDelete,
  onTested,
}: {
  provider: AIProvider;
  model: AIModel;
  onDelete: (m: AIModel) => void;
  onTested: (r: ConnectionTestResult) => void;
}) {
  const update = useUpdateModel();
  const test = useTestConnection();
  return (
    <li className="flex flex-col gap-2 py-2.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={model.enabled ? "font-mono text-[13px]" : "font-mono text-[13px] text-muted-foreground line-through"}>
            {model.model_identifier}
          </span>
          {model.health_state !== "unknown" && model.health_state !== "healthy" ? (
            <HealthBadge state={model.health_state} />
          ) : null}
          {model.circuit_open ? <Badge tone="warning">Paused after failures</Badge> : null}
          {model.route_roles.map((r) => (
            <Badge key={r} tone="accent">
              {ROLE_META[r].label}
            </Badge>
          ))}
        </div>
        {model.last_error_message && model.health_state !== "healthy" ? (
          <p className="truncate text-[12px] text-muted-foreground" title={model.last_error_message}>
            {model.last_error_message}
          </p>
        ) : null}
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          size="sm"
          variant="ghost"
          disabled={test.isPending}
          onClick={() =>
            test.mutate(
              { id: provider.id, modelId: model.id },
              { onSuccess: onTested, onError: (e) => toast.error(errorMessage(e)) },
            )
          }
        >
          {test.isPending ? <Spinner /> : <Plug />} Test
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={update.isPending}
          onClick={() =>
            update.mutate(
              { id: model.id, input: { enabled: !model.enabled } },
              { onError: (e) => toast.error(errorMessage(e)) },
            )
          }
        >
          {model.enabled ? "Disable" : "Enable"}
        </Button>
        <Button size="icon-sm" variant="ghost" aria-label={`Remove ${model.model_identifier}`} onClick={() => onDelete(model)}>
          <Trash2 />
        </Button>
      </div>
    </li>
  );
}

export function ProviderCard({ provider, actions }: { provider: AIProvider; actions: ProviderActions }) {
  const test = useTestConnection();
  const update = useUpdateProvider();
  const [result, setResult] = useState<ConnectionTestResult | null>(null);

  const runTest = () =>
    test.mutate(
      { id: provider.id },
      { onSuccess: setResult, onError: (e) => toast.error(errorMessage(e)) },
    );

  return (
    <Card className={provider.enabled ? "" : "opacity-75"}>
      <div className="flex flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold">{provider.display_name}</h3>
            <Badge>{provider.provider_label}</Badge>
            <HealthBadge state={provider.health_state} />
            {!provider.enabled ? <Badge tone="neutral">Disabled</Badge> : null}
          </div>
          <dl className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
            <div className="flex gap-1">
              <dt>Key:</dt>
              <dd className="font-mono">{provider.key_masked ?? "none"}</dd>
            </div>
            <div className="flex min-w-0 gap-1">
              <dt>Endpoint:</dt>
              <dd className="truncate font-mono" title={provider.effective_base_url}>
                {provider.effective_base_url}
              </dd>
            </div>
            <div className="flex gap-1">
              <dt>Tested:</dt>
              <dd>{provider.last_tested_at ? formatRelative(provider.last_tested_at) : "never"}</dd>
            </div>
          </dl>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button size="sm" variant="outline" onClick={runTest} disabled={test.isPending || provider.models.length === 0}>
            {test.isPending ? <Spinner /> : <Plug />} Test connection
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label={`More actions for ${provider.display_name}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onSelect={() =>
                  update.mutate(
                    { id: provider.id, input: { enabled: !provider.enabled } },
                    {
                      onSuccess: (p) => toast.success(p.enabled ? "Provider enabled" : "Provider disabled"),
                      onError: (e) => toast.error(errorMessage(e)),
                    },
                  )
                }
              >
                <Power /> {provider.enabled ? "Disable" : "Enable"}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => actions.onEdit(provider)}>
                <Pencil /> Edit name or URL
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => actions.onReplaceKey(provider)}>
                <KeyRound /> {provider.has_key ? "Replace API key" : "Add API key"}
              </DropdownMenuItem>
              {provider.has_key ? (
                <DropdownMenuItem onSelect={() => actions.onRemoveKey(provider)}>
                  <KeyRound /> Delete API key
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" onSelect={() => actions.onDelete(provider)}>
                <Trash2 /> Delete provider
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <div className="space-y-3 px-5 py-4">
        {result ? <TestResult result={result} /> : null}
        {!result && provider.last_error_message && provider.health_state !== "healthy" && provider.health_state !== "unknown" ? (
          <p className="text-[13px] text-muted-foreground">
            Last error{provider.last_error_at ? ` ${formatRelative(provider.last_error_at)}` : ""}:{" "}
            {provider.last_error_message}
          </p>
        ) : null}
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Models</p>
          {provider.models.length ? (
            <ul className="divide-y">
              {provider.models.map((m) => (
                <ModelRow
                  key={m.id}
                  provider={provider}
                  model={m}
                  onDelete={actions.onDeleteModel}
                  onTested={setResult}
                />
              ))}
            </ul>
          ) : (
            <p className="py-2 text-sm text-muted-foreground">No models yet. Add one to use this provider.</p>
          )}
        </div>
        <AddModelForm provider={provider} />
      </div>
    </Card>
  );
}
