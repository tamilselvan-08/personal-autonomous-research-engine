"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { ApiError, errorMessage } from "@/lib/api-client";

type Mode = "login" | "register";

function safeNext(value: string | null): string {
  // Only allow same-app relative paths to avoid open redirects.
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export function AuthForm({ mode }: { mode: Mode }) {
  const { user, login, register } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (user) router.replace(next);
  }, [user, router, next]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFieldErrors({});
    setFormError(null);
    if (mode === "register" && password.length < 10) {
      setFieldErrors({ password: "Use at least 10 characters." });
      return;
    }
    setPending(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, displayName);
      router.replace(next);
    } catch (error) {
      if (error instanceof ApiError && error.fieldErrors.length) {
        setFieldErrors(error.fieldMessages());
      } else {
        setFormError(errorMessage(error));
      }
    } finally {
      setPending(false);
    }
  }

  const isLogin = mode === "login";
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{isLogin ? "Sign in" : "Create your account"}</CardTitle>
        <CardDescription>
          {isLogin
            ? "Use the local account you created for PARE."
            : "This creates a local account on this machine. No data leaves your computer."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          {!isLogin ? (
            <Field id="display_name" label="Name" error={fieldErrors.display_name} required>
              <Input
                id="display_name"
                autoComplete="name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                aria-invalid={!!fieldErrors.display_name}
                required
                maxLength={100}
              />
            </Field>
          ) : null}
          <Field id="email" label="Email" error={fieldErrors.email} required>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={!!fieldErrors.email}
              required
            />
          </Field>
          <Field
            id="password"
            label="Password"
            error={fieldErrors.password}
            hint={!isLogin ? "At least 10 characters, mixing letters with numbers or symbols." : undefined}
            required
          >
            <Input
              id="password"
              type="password"
              autoComplete={isLogin ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={!!fieldErrors.password}
              required
              maxLength={128}
            />
          </Field>
          {formError ? (
            <p role="alert" className="text-sm text-destructive">
              {formError}
            </p>
          ) : null}
          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? "Please wait…" : isLogin ? "Sign in" : "Create account"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          {isLogin ? (
            <>
              No account yet?{" "}
              <Link href="/register" className="font-medium text-primary hover:underline">
                Create one
              </Link>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <Link href="/login" className="font-medium text-primary hover:underline">
                Sign in
              </Link>
            </>
          )}
        </p>
      </CardContent>
    </Card>
  );
}
