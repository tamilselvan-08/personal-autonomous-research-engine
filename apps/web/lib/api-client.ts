import type { ErrorEnvelope, FieldError } from "@/types/api";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: FieldError[];
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.fieldErrors = Array.isArray(details.fields) ? (details.fields as FieldError[]) : [];
    this.requestId = requestId;
  }

  /** Map of field name → first error message, for form display. */
  fieldMessages(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const err of this.fieldErrors) {
      const field = String(err.loc[err.loc.length - 1] ?? "");
      if (field && !(field in out)) out[field] = err.msg.replace(/^Value error, /, "");
    }
    return out;
  }
}

export class NetworkError extends Error {
  constructor() {
    super(`Cannot reach the PARE backend at ${API_BASE_URL}. Check that the API is running.`);
    this.name = "NetworkError";
  }
}

type Query = Record<string, string | number | boolean | null | undefined | string[]>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

export function buildUrl(path: string, query?: Query): string {
  const url = new URL(`${API_BASE_URL}/api/v1${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v));
      else url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

function isEnvelope(value: unknown): value is ErrorEnvelope {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ErrorEnvelope).error?.code === "string"
  );
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-PARE-CSRF"] = "1";
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      credentials: "include",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError();
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    if (isEnvelope(data)) {
      const { code, message, details, request_id } = data.error;
      throw new ApiError(response.status, code, message, details, request_id);
    }
    throw new ApiError(response.status, "HTTP_ERROR", `Request failed (${response.status}).`);
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError) return error.message;
  return "Something went wrong. Please try again.";
}
