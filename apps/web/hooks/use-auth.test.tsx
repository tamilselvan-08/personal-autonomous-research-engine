import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/hooks/use-auth";

const USER = { id: "u1", email: "priya@example.com", display_name: "Priya", created_at: "" };

function Probe() {
  const { user, logout } = useAuth();
  return (
    <div>
      <span data-testid="user">{user ? user.email : "signed-out"}</span>
      <button onClick={() => void logout()}>logout</button>
    </div>
  );
}

function setup(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>,
  );
  return client;
}

afterEach(() => vi.unstubAllGlobals());

describe("AuthProvider", () => {
  it("treats 401 from /auth/me as signed out", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "x", details: {}, request_id: null } }),
            { status: 401 },
          ),
        ),
      ),
    );
    setup(<Probe />);
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("signed-out"));
  });

  it("clears the user and other cached data on logout (regression)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url.endsWith("/auth/logout")
            ? new Response(null, { status: 204 })
            : new Response(JSON.stringify(USER), { status: 200 }),
        ),
      ),
    );
    const client = setup(<Probe />);
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));
    client.setQueryData(["tasks", "stats"], { total: 3 });

    await act(async () => screen.getByText("logout").click());

    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("signed-out"));
    expect(client.getQueryData(["tasks", "stats"])).toBeUndefined();
  });
});
