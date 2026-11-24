import Link from "next/link";
import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: { href: string; label: string };
}

export function PageHeader({ title, description, actions, breadcrumb }: PageHeaderProps) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0 space-y-1">
        {breadcrumb ? (
          <Link
            href={breadcrumb.href}
            className="text-[13px] text-muted-foreground hover:text-foreground"
          >
            ← {breadcrumb.label}
          </Link>
        ) : null}
        <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
