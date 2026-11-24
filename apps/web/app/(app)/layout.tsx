"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { ErrorState, Spinner } from "@/components/ui/misc";
import { useAuth } from "@/hooks/use-auth";
import { errorMessage } from "@/lib/api-client";

export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const { user, isLoading, error, refetch } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !error && !user) {
      const next = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${next}`);
    }
  }, [isLoading, error, user, router, pathname]);

  if (error) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-6">
        <ErrorState
          className="max-w-md"
          title="Can't reach PARE"
          message={errorMessage(error)}
          onRetry={refetch}
        />
      </div>
    );
  }

  if (isLoading || !user) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-muted-foreground">
        <Spinner />
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}
