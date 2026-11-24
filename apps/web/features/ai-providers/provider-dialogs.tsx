"use client";

import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import {
  useDeleteModel,
  useDeleteProvider,
  useRemoveKey,
  useReplaceKey,
  useUpdateProvider,
} from "@/features/ai-providers/hooks";
import { ApiError, errorMessage } from "@/lib/api-client";
import type { AIModel, AIProvider } from "@/types/api";

function EditBody({ provider, onDone }: { provider: AIProvider; onDone: () => void }) {
  const update = useUpdateProvider();
  const [name, setName] = useState(provider.display_name);
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    if (!name.trim()) return setErrors({ display_name: "Name is required." });
    try {
      await update.mutateAsync({
        id: provider.id,
        input: { display_name: name.trim(), base_url: baseUrl.trim() || null },
      });
      toast.success("Provider updated");
      onDone();
    } catch (error) {
      if (error instanceof ApiError && error.code === "PROVIDER_NAME_TAKEN")
        setErrors({ display_name: error.message });
      else if (error instanceof ApiError && error.fieldErrors.length) setErrors(error.fieldMessages());
      else setFormError(errorMessage(error));
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <Field id="edit-provider-name" label="Name" error={errors.display_name} required>
        <Input
          id="edit-provider-name"
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.target.value)}
          aria-invalid={!!errors.display_name}
        />
      </Field>
      <Field
        id="edit-provider-url"
        label="Base URL"
        error={errors.base_url}
        hint={`Leave empty to use ${provider.effective_base_url && !provider.base_url ? provider.effective_base_url : "the provider default"}.`}
      >
        <Input
          id="edit-provider-url"
          value={baseUrl}
          placeholder={provider.effective_base_url}
          onChange={(e) => setBaseUrl(e.target.value)}
          aria-invalid={!!errors.base_url}
        />
      </Field>
      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function EditProviderDialog({
  provider,
  onOpenChange,
}: {
  provider: AIProvider | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={provider !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit provider</DialogTitle>
          <DialogDescription>Changing the base URL resets its health status.</DialogDescription>
        </DialogHeader>
        {provider ? <EditBody key={provider.id} provider={provider} onDone={() => onOpenChange(false)} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function KeyBody({ provider, onDone }: { provider: AIProvider; onDone: () => void }) {
  const replace = useReplaceKey();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!key.trim()) return setError("Enter the new API key.");
    if (/\s/.test(key.trim())) return setError("The key must not contain spaces.");
    try {
      const updated = await replace.mutateAsync({ id: provider.id, apiKey: key.trim() });
      setKey("");
      toast.success(`Key replaced (${updated.key_masked})`);
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? (e.fieldMessages().api_key ?? e.message) : errorMessage(e));
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <Field
        id="replace-key"
        label="New API key"
        required
        error={error ?? undefined}
        hint={provider.key_masked ? `Replaces ${provider.key_masked}. The old key is deleted.` : undefined}
      >
        <Input
          id="replace-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          aria-invalid={!!error}
          autoFocus
        />
      </Field>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={replace.isPending}>
          {replace.isPending ? "Saving…" : "Save key"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function ReplaceKeyDialog({
  provider,
  onOpenChange,
}: {
  provider: AIProvider | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={provider !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{provider?.has_key ? "Replace API key" : "Add API key"}</DialogTitle>
          <DialogDescription>
            The key is encrypted before it is stored and is never shown again.
          </DialogDescription>
        </DialogHeader>
        {provider ? <KeyBody key={provider.id} provider={provider} onDone={() => onOpenChange(false)} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function usedIn(provider: AIProvider): string[] {
  return [...new Set(provider.models.flatMap((m) => m.route_roles))];
}

export function DeleteProviderDialog({
  provider,
  onOpenChange,
}: {
  provider: AIProvider | null;
  onOpenChange: (open: boolean) => void;
}) {
  const del = useDeleteProvider();
  const roles = provider ? usedIn(provider) : [];
  return (
    <ConfirmDialog
      open={provider !== null}
      onOpenChange={(open) => {
        if (!open) del.reset();
        onOpenChange(open);
      }}
      title="Delete provider?"
      description={
        <>
          <span className="font-medium text-foreground">{provider?.display_name}</span>, its models
          and its stored API key will be permanently deleted.
          {roles.length ? ` Its models will also be removed from routing (${roles.join(", ")}).` : ""}{" "}
          Usage history is kept.
        </>
      }
      confirmLabel="Delete provider"
      pendingLabel="Deleting…"
      destructive
      pending={del.isPending}
      error={del.isError ? errorMessage(del.error) : null}
      onConfirm={() => {
        if (!provider) return;
        del.mutate(
          { id: provider.id, force: roles.length > 0 },
          {
            onSuccess: () => {
              toast.success("Provider deleted");
              onOpenChange(false);
            },
          },
        );
      }}
    />
  );
}

export function RemoveKeyDialog({
  provider,
  onOpenChange,
}: {
  provider: AIProvider | null;
  onOpenChange: (open: boolean) => void;
}) {
  const remove = useRemoveKey();
  return (
    <ConfirmDialog
      open={provider !== null}
      onOpenChange={(open) => {
        if (!open) remove.reset();
        onOpenChange(open);
      }}
      title="Delete stored API key?"
      description={
        <>
          The key {provider?.key_masked} for{" "}
          <span className="font-medium text-foreground">{provider?.display_name}</span> will be
          permanently deleted. Routing skips this provider until you add a new key.
        </>
      }
      confirmLabel="Delete key"
      pendingLabel="Deleting…"
      destructive
      pending={remove.isPending}
      error={remove.isError ? errorMessage(remove.error) : null}
      onConfirm={() => {
        if (!provider) return;
        remove.mutate(provider.id, {
          onSuccess: () => {
            toast.success("API key deleted");
            onOpenChange(false);
          },
        });
      }}
    />
  );
}

export function DeleteModelDialog({
  model,
  onOpenChange,
}: {
  model: AIModel | null;
  onOpenChange: (open: boolean) => void;
}) {
  const del = useDeleteModel();
  const roles = model?.route_roles ?? [];
  return (
    <ConfirmDialog
      open={model !== null}
      onOpenChange={(open) => {
        if (!open) del.reset();
        onOpenChange(open);
      }}
      title="Remove model?"
      description={
        <>
          <span className="font-mono text-foreground">{model?.model_identifier}</span> will be
          removed from this provider
          {roles.length ? ` and from routing (${roles.join(", ")})` : ""}.
        </>
      }
      confirmLabel="Remove model"
      pendingLabel="Removing…"
      destructive
      pending={del.isPending}
      error={del.isError ? errorMessage(del.error) : null}
      onConfirm={() => {
        if (!model) return;
        del.mutate(
          { id: model.id, force: roles.length > 0 },
          {
            onSuccess: () => {
              toast.success("Model removed");
              onOpenChange(false);
            },
          },
        );
      }}
    />
  );
}
