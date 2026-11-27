import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AddProviderDialog,
  toCreateInput,
  validateProviderForm,
  type ProviderFormValues,
} from "@/features/ai-providers/add-provider-dialog";
import {
  ROLE_META,
  formatCost,
  formatMs,
  formatPercent,
  formatTokens,
  healthMeta,
} from "@/features/ai-providers/meta";
import { ProviderCard } from "@/features/ai-providers/provider-card";
import { moveItem } from "@/features/ai-providers/routing-card";
import { MODEL_ROLES, type AIProvider, type ProviderTypeInfo } from "@/types/api";

const OPENAI: ProviderTypeInfo = {
  type: "openai",
  label: "OpenAI",
  protocol: "openai",
  default_base_url: "https://api.openai.com/v1",
  requires_base_url: false,
  api_key_required: true,
  allow_http: false,
  key_hint: "Starts with sk-",
  docs_url: "https://platform.openai.com/api-keys",
  model_examples: ["gpt-4o-mini"],
  verification: "mocked",
};
const COMPATIBLE: ProviderTypeInfo = {
  ...OPENAI,
  type: "openai_compatible",
  label: "OpenAI-compatible endpoint",
  default_base_url: null,
  requires_base_url: true,
  api_key_required: false,
  allow_http: true,
  docs_url: null,
};

const base: ProviderFormValues = {
  providerType: "openai",
  displayName: "OpenAI",
  apiKey: "sk-abc",
  baseUrl: "",
  modelIdentifier: "gpt-4o-mini",
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => vi.unstubAllGlobals());

describe("validateProviderForm", () => {
  it("accepts a complete form", () => {
    expect(validateProviderForm(base, OPENAI)).toEqual({});
  });

  it("requires a key, name and a valid model id", () => {
    const errors = validateProviderForm(
      { ...base, apiKey: "", displayName: " ", modelIdentifier: "gpt 4" },
      OPENAI,
    );
    expect(Object.keys(errors).sort()).toEqual(["api_key", "display_name", "model_identifier"]);
  });

  it("requires https for hosted providers but allows http for compatible endpoints", () => {
    expect(validateProviderForm({ ...base, baseUrl: "http://x.test/v1" }, OPENAI).base_url).toBeDefined();
    const local = { ...base, providerType: "openai_compatible" as const, apiKey: "" };
    expect(validateProviderForm(local, COMPATIBLE).base_url).toMatch(/endpoint URL/);
    expect(validateProviderForm({ ...local, baseUrl: "http://localhost:1234/v1" }, COMPATIBLE)).toEqual({});
  });

  it("builds the create payload without empty fields", () => {
    expect(toCreateInput({ ...base, apiKey: "  sk-abc  ", displayName: " Work " })).toEqual({
      provider_type: "openai",
      display_name: "Work",
      api_key: "sk-abc",
      models: [{ model_identifier: "gpt-4o-mini" }],
    });
    expect(toCreateInput({ ...base, apiKey: "" })).not.toHaveProperty("api_key");
  });
});

describe("AddProviderDialog", () => {
  it("uses a password field and sends the provider to the API", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/providers") && init?.method === "POST") {
        return Promise.resolve(
          new Response(
            JSON.stringify({ id: "p1", display_name: "OpenAI", models: [{ id: "m1" }] }),
            { status: 201 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<AddProviderDialog open onOpenChange={() => {}} types={[OPENAI, COMPATIBLE]} />, { wrapper });

    const key = screen.getByLabelText(/API key/);
    expect(key).toHaveAttribute("type", "password");
    expect(key).toHaveAttribute("autocomplete", "off");

    await user.type(key, "sk-secret-value");
    await user.type(screen.getByLabelText(/Model ID/), "gpt-4o-mini");
    await user.click(screen.getByLabelText(/Test the connection/));
    await user.click(screen.getByRole("button", { name: "Add provider" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(JSON.parse(String(init!.body))).toEqual({
      provider_type: "openai",
      display_name: "OpenAI",
      api_key: "sk-secret-value",
      models: [{ model_identifier: "gpt-4o-mini" }],
    });
    expect((init!.headers as Record<string, string>)["X-PARE-CSRF"]).toBe("1");
  });

  it("shows the base URL field and validation for compatible endpoints", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const user = userEvent.setup();
    render(<AddProviderDialog open onOpenChange={() => {}} types={[OPENAI, COMPATIBLE]} />, { wrapper });
    await user.selectOptions(screen.getByLabelText(/Provider/), "openai_compatible");
    expect(screen.getByLabelText(/Base URL/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add provider" }));
    expect(await screen.findByText(/Enter the endpoint URL/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});

const PROVIDER: AIProvider = {
  id: "p1",
  provider_type: "openai",
  provider_label: "OpenAI",
  display_name: "Work OpenAI",
  base_url: null,
  effective_base_url: "https://api.openai.com/v1",
  enabled: true,
  has_key: true,
  key_masked: "••••7890",
  key_updated_at: "2026-11-25T00:00:00Z",
  health_state: "invalid_credentials",
  connection_status: "failing",
  consecutive_failures: 0,
  last_error_class: "auth",
  last_error_message: "Incorrect API key provided",
  last_error_at: "2026-11-25T00:00:00Z",
  last_success_at: null,
  last_tested_at: null,
  verification: "mocked",
  models: [
    {
      id: "m1",
      provider_id: "p1",
      model_identifier: "gpt-4o-mini",
      display_name: null,
      context_window: 128000,
      input_price_per_mtok: null,
      output_price_per_mtok: null,
      supports_json: true,
      capabilities: ["json", "vision"],
      enabled: true,
      health_state: "unknown",
      last_error_class: null,
      last_error_message: null,
      last_error_at: null,
      last_success_at: null,
      circuit_open: false,
      route_roles: ["default"],
      created_at: "",
      updated_at: "",
    },
  ],
  created_at: "",
  updated_at: "",
};

describe("ProviderCard", () => {
  it("shows only the masked key and the health problem", () => {
    const noop = () => {};
    render(
      <ProviderCard
        provider={PROVIDER}
        actions={{ onEdit: noop, onReplaceKey: noop, onRemoveKey: noop, onDelete: noop, onDeleteModel: noop }}
      />,
      { wrapper },
    );
    expect(screen.getByText("••••7890")).toBeInTheDocument();
    expect(screen.getByText("Key rejected")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByText("128k context · JSON · Vision")).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("moves chain items and ignores out-of-range moves", () => {
    expect(moveItem(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
  });

  it("formats values", () => {
    expect(formatCost(null)).toBe("—");
    expect(formatCost("0.000045")).toBe("$0.00005");
    expect(formatCost("1.5")).toBe("$1.50");
    expect(formatMs(1530)).toBe("1.5 s");
    expect(formatMs(42.4)).toBe("42 ms");
    expect(formatPercent(0.6667)).toBe("67%");
    expect(healthMeta("nonsense").label).toBe("Not tested");
    expect(formatTokens(128000)).toBe("128k");
    expect(formatTokens(1048576)).toBe("1M");
    expect(formatTokens(512)).toBe("512");
  });

  it("labels every task role, including researcher", () => {
    expect(MODEL_ROLES).toEqual(["default", "planner", "researcher", "extractor", "verifier", "summarizer"]);
    for (const role of MODEL_ROLES) expect(ROLE_META[role].label).toBeTruthy();
  });
});
