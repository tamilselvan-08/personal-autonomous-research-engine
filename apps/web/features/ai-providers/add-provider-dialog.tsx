"use client";

import { ExternalLink } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { useCreateProvider, useTestConnection } from "@/features/ai-providers/hooks";
import { ApiError, errorMessage } from "@/lib/api-client";
import type { ProviderCreateInput, ProviderType, ProviderTypeInfo } from "@/types/api";

export const MODEL_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$/;

export interface ProviderFormValues {
  providerType: ProviderType;
  displayName: string;
  apiKey: string;
  baseUrl: string;
  modelIdentifier: string;
}

/** Client-side checks that mirror the API's validation, for immediate feedback. */
export function validateProviderForm(
  values: ProviderFormValues,
  info: ProviderTypeInfo | undefined,
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!values.displayName.trim()) errors.display_name = "Give this provider a name.";
  if (info?.api_key_required && !values.apiKey.trim()) errors.api_key = "Enter the API key.";
  if (/\s/.test(values.apiKey.trim())) errors.api_key = "The key must not contain spaces.";
  const url = values.baseUrl.trim();
  if (info?.requires_base_url && !url) {
    errors.base_url = "Enter the endpoint URL, e.g. http://localhost:1234/v1";
  } else if (url) {
    const ok = info?.allow_http ? /^https?:\/\/\S+$/i : /^https:\/\/\S+$/i;
    if (!ok.test(url)) {
      errors.base_url = info?.allow_http ? "Use an http:// or https:// URL." : "Use an https:// URL.";
    }
  }
  const model = values.modelIdentifier.trim();
  if (!model) errors.model_identifier = "Enter at least one model ID.";
  else if (!MODEL_ID_PATTERN.test(model) || model.includes(".."))
    errors.model_identifier = "Use the provider's model ID exactly (no spaces).";
  return errors;
}

export function toCreateInput(values: ProviderFormValues): ProviderCreateInput {
  const input: ProviderCreateInput = {
    provider_type: values.providerType,
    display_name: values.displayName.trim(),
    models: [{ model_identifier: values.modelIdentifier.trim() }],
  };
  if (values.apiKey.trim()) input.api_key = values.apiKey.trim();
  if (values.baseUrl.trim()) input.base_url = values.baseUrl.trim();
  return input;
}

function FormBody({ types, onDone }: { types: ProviderTypeInfo[]; onDone: () => void }) {
  const create = useCreateProvider();
  const test = useTestConnection();
  const [values, setValues] = useState<ProviderFormValues>({
    providerType: types[0]?.type ?? "openai",
    displayName: types[0]?.label ?? "",
    apiKey: "",
    baseUrl: "",
    modelIdentifier: "",
  });
  const [nameEdited, setNameEdited] = useState(false);
  const [showBaseUrl, setShowBaseUrl] = useState(false);
  const [testAfter, setTestAfter] = useState(true);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const info = types.find((t) => t.type === values.providerType);
  const set = (patch: Partial<ProviderFormValues>) => setValues((v) => ({ ...v, ...patch }));

  function changeType(type: ProviderType) {
    const next = types.find((t) => t.type === type);
    set({ providerType: type, ...(nameEdited ? {} : { displayName: next?.label ?? "" }) });
    setShowBaseUrl(Boolean(next?.requires_base_url));
    setErrors({});
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const found = validateProviderForm(values, info);
    setErrors(found);
    if (Object.keys(found).length) return;
    try {
      const provider = await create.mutateAsync(toCreateInput(values));
      // The key now exists only encrypted on the server; drop it from memory.
      set({ apiKey: "" });
      toast.success(`${provider.display_name} added`);
      onDone();
      if (testAfter) {
        test.mutate(
          { id: provider.id, modelId: provider.models[0]?.id },
          {
            onSuccess: (r) =>
              r.ok
                ? toast.success(`${provider.display_name}: connected (${r.latency_ms} ms)`)
                : toast.error(`${provider.display_name}: ${r.error_hint ?? r.message}`),
            onError: (e) => toast.error(errorMessage(e)),
          },
        );
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "PROVIDER_NAME_TAKEN") {
        setErrors({ display_name: error.message });
      } else if (error instanceof ApiError && error.fieldErrors.length) {
        setErrors(error.fieldMessages());
      } else {
        setFormError(errorMessage(error));
      }
    }
  }

  const example = info?.model_examples[0];
  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <Field id="provider-type" label="Provider" required>
        <NativeSelect
          id="provider-type"
          value={values.providerType}
          onChange={(e) => changeType(e.target.value as ProviderType)}
        >
          {types.map((t) => (
            <option key={t.type} value={t.type}>
              {t.label}
            </option>
          ))}
        </NativeSelect>
      </Field>

      <Field id="provider-name" label="Name" error={errors.display_name} required hint="Shown in routing and usage.">
        <Input
          id="provider-name"
          value={values.displayName}
          maxLength={100}
          aria-invalid={!!errors.display_name}
          onChange={(e) => {
            setNameEdited(true);
            set({ displayName: e.target.value });
          }}
        />
      </Field>

      <Field
        id="provider-key"
        label="API key"
        required={info?.api_key_required}
        error={errors.api_key}
        hint={
          <span className="inline-flex flex-wrap items-center gap-1">
            {info?.key_hint ? `${info.key_hint}. ` : ""}Encrypted on save and never shown again.
            {info?.docs_url ? (
              <a
                href={info.docs_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-0.5 text-primary hover:underline"
              >
                Get a key <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : null}
          </span>
        }
      >
        <Input
          id="provider-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={values.apiKey}
          aria-invalid={!!errors.api_key}
          onChange={(e) => set({ apiKey: e.target.value })}
        />
      </Field>

      {showBaseUrl || info?.requires_base_url ? (
        <Field
          id="provider-base-url"
          label="Base URL"
          required={info?.requires_base_url}
          error={errors.base_url}
          hint={
            info?.requires_base_url
              ? "The /v1 endpoint of your server. From Docker, use host.docker.internal instead of localhost."
              : `Leave empty for ${info?.default_base_url ?? "the default"}.`
          }
        >
          <Input
            id="provider-base-url"
            value={values.baseUrl}
            placeholder={info?.default_base_url ?? "http://localhost:1234/v1"}
            aria-invalid={!!errors.base_url}
            onChange={(e) => set({ baseUrl: e.target.value })}
          />
        </Field>
      ) : (
        <button
          type="button"
          className="text-[13px] text-muted-foreground hover:text-foreground"
          onClick={() => setShowBaseUrl(true)}
        >
          Use a custom base URL…
        </button>
      )}

      <Field
        id="provider-model"
        label="Model ID"
        required
        error={errors.model_identifier}
        hint={`Exactly as the provider names it${example ? `, e.g. ${example}` : ""}. You can add more models later.`}
      >
        <Input
          id="provider-model"
          value={values.modelIdentifier}
          maxLength={200}
          spellCheck={false}
          aria-invalid={!!errors.model_identifier}
          onChange={(e) => set({ modelIdentifier: e.target.value })}
        />
      </Field>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={testAfter} onChange={(e) => setTestAfter(e.target.checked)} />
        Test the connection after saving
      </label>

      {formError ? (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Saving…" : "Add provider"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function AddProviderDialog({
  open,
  onOpenChange,
  types,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  types: ProviderTypeInfo[];
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Add AI provider</DialogTitle>
          <DialogDescription>Connect an account you own. PARE calls it directly with your key.</DialogDescription>
        </DialogHeader>
        {open ? <FormBody types={types} onDone={() => onOpenChange(false)} /> : null}
      </DialogContent>
    </Dialog>
  );
}
