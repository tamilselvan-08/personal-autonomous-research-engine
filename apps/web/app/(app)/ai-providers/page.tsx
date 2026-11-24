"use client";

import { Bot, Plus, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/misc";
import { AddProviderDialog } from "@/features/ai-providers/add-provider-dialog";
import { useProviderTypes, useProviders } from "@/features/ai-providers/hooks";
import { ProviderCard } from "@/features/ai-providers/provider-card";
import {
  DeleteModelDialog,
  DeleteProviderDialog,
  EditProviderDialog,
  RemoveKeyDialog,
  ReplaceKeyDialog,
} from "@/features/ai-providers/provider-dialogs";
import { RoutingCard } from "@/features/ai-providers/routing-card";
import { HealthCard, UsageCard } from "@/features/ai-providers/usage-card";
import { errorMessage } from "@/lib/api-client";
import type { AIModel, AIProvider } from "@/types/api";

export default function AIProvidersPage() {
  const types = useProviderTypes();
  const providers = useProviders();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<AIProvider | null>(null);
  const [keyFor, setKeyFor] = useState<AIProvider | null>(null);
  const [removeKeyFor, setRemoveKeyFor] = useState<AIProvider | null>(null);
  const [deleting, setDeleting] = useState<AIProvider | null>(null);
  const [deletingModel, setDeletingModel] = useState<AIModel | null>(null);

  const encryptionMissing = types.data && !types.data.encryption_configured;
  const list = providers.data ?? [];

  return (
    <>
      <PageHeader
        title="AI Providers"
        description="Connect your own model accounts and choose which one PARE uses first."
        actions={
          <Button onClick={() => setAdding(true)} disabled={!types.data}>
            <Plus /> Add provider
          </Button>
        }
      />

      {encryptionMissing ? (
        <div
          role="alert"
          className="mb-6 flex gap-3 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm"
        >
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <div>
            <p className="font-medium">API keys can&apos;t be saved yet</p>
            <p className="text-muted-foreground">
              The server has no encryption key. Run <code className="font-mono">scripts\setup-env.ps1</code>{" "}
              (it adds <code className="font-mono">SECRETS_MASTER_KEY</code> to your .env) and restart
              PARE. Keyless local endpoints still work.
            </p>
          </div>
        </div>
      ) : null}

      <div className="grid gap-6">
        {providers.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : providers.isError ? (
          <ErrorState message={errorMessage(providers.error)} onRetry={() => void providers.refetch()} />
        ) : list.length === 0 ? (
          <Card>
            <EmptyState
              icon={Bot}
              title="No AI providers yet"
              description="Add at least one provider and model. Add two or more to get automatic fallback when one is unavailable."
              action={
                <Button onClick={() => setAdding(true)} disabled={!types.data}>
                  <Plus /> Add provider
                </Button>
              }
            />
          </Card>
        ) : (
          <>
            <RoutingCard providers={list} />
            <section aria-label="Providers" className="grid gap-4">
              {list.map((p) => (
                <ProviderCard
                  key={p.id}
                  provider={p}
                  actions={{
                    onEdit: setEditing,
                    onReplaceKey: setKeyFor,
                    onRemoveKey: setRemoveKeyFor,
                    onDelete: setDeleting,
                    onDeleteModel: setDeletingModel,
                  }}
                />
              ))}
            </section>
            <HealthCard />
            <UsageCard />
          </>
        )}
        <p className="text-[13px] text-muted-foreground">
          Provider integrations are tested against recorded API responses. They have not yet been
          verified live against every provider; run a connection test to confirm yours.
        </p>
      </div>

      {types.data ? (
        <AddProviderDialog open={adding} onOpenChange={setAdding} types={types.data.types} />
      ) : null}
      <EditProviderDialog provider={editing} onOpenChange={(o) => !o && setEditing(null)} />
      <ReplaceKeyDialog provider={keyFor} onOpenChange={(o) => !o && setKeyFor(null)} />
      <RemoveKeyDialog provider={removeKeyFor} onOpenChange={(o) => !o && setRemoveKeyFor(null)} />
      <DeleteProviderDialog provider={deleting} onOpenChange={(o) => !o && setDeleting(null)} />
      <DeleteModelDialog model={deletingModel} onOpenChange={(o) => !o && setDeletingModel(null)} />
    </>
  );
}
