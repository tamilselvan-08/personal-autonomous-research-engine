import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-sidebar px-4 py-12">
      <div className="mb-8 flex items-center gap-2 text-lg font-semibold tracking-tight">
        <span
          aria-hidden
          className="flex size-7 items-center justify-center rounded-md bg-primary font-mono text-xs font-bold text-primary-foreground"
        >
          P
        </span>
        PARE
      </div>
      <div className="w-full max-w-sm">{children}</div>
      <p className="mt-8 max-w-sm text-center text-xs text-muted-foreground">
        Personal Autonomous Research Engine. Your account and data are stored on this machine.
      </p>
    </div>
  );
}
