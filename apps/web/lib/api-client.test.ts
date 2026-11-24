import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, NetworkError, apiRequest, buildUrl } from "@/lib/api-client";

function mockFetch(response: Response | Error) {
  // Clone per call: a Response body can only be read once.
  const fn = vi.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response.clone()),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildUrl", () => {
  it("prefixes the API version and drops empty params", () => {
    const url = new URL(buildUrl("/tasks", { q: "", page: 2, project_id: undefined }));
    expect(url.pathname).toBe("/api/v1/tasks");
    expect(url.searchParams.get("page")).toBe("2");
    expect(url.searchParams.has("q")).toBe(false);
    expect(url.searchParams.has("project_id")).toBe(false);
  });

  it("repeats array params", () => {
    const url = new URL(buildUrl("/tasks", { status: ["draft", "completed"] }));
    expect(url.searchParams.getAll("status")).toEqual(["draft", "completed"]);
  });
});

describe("apiRequest", () => {
  it("sends credentials and the CSRF header only on unsafe methods", async () => {
    const fetchFn = mockFetch(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    await apiRequest("/tasks");
    await apiRequest("/tasks", { method: "POST", body: { title: "x" } });

    const [, getInit] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    const [, postInit] = fetchFn.mock.calls[1] as unknown as [string, RequestInit];
    expect(getInit.credentials).toBe("include");
    expect((getInit.headers as Record<string, string>)["X-PARE-CSRF"]).toBeUndefined();
    expect((postInit.headers as Record<string, string>)["X-PARE-CSRF"]).toBe("1");
    expect((postInit.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(postInit.body).toBe(JSON.stringify({ title: "x" }));
  });

  it("returns undefined for 204", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(apiRequest("/tasks/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("parses the error envelope including field errors", async () => {
    mockFetch(
      new Response(
        JSON.stringify({
          error: {
            code: "VALIDATION_ERROR",
            message: "Request validation failed.",
            details: {
              fields: [
                { loc: ["body", "title"], msg: "Value error, Title is required.", type: "value_error" },
              ],
            },
            request_id: "r1",
          },
        }),
        { status: 422 },
      ),
    );
    const error = (await apiRequest("/tasks", { method: "POST", body: {} }).catch((e) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(422);
    expect(error.code).toBe("VALIDATION_ERROR");
    expect(error.requestId).toBe("r1");
    expect(error.fieldMessages()).toEqual({ title: "Title is required." });
  });

  it("handles non-JSON error bodies", async () => {
    mockFetch(new Response("<html>bad gateway</html>", { status: 502 }));
    const error = (await apiRequest("/tasks").catch((e) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.code).toBe("HTTP_ERROR");
  });

  it("converts fetch failures into a NetworkError", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    await expect(apiRequest("/tasks")).rejects.toBeInstanceOf(NetworkError);
  });
});
