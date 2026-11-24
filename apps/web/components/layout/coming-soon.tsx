import type { LucideIcon } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";

interface ComingSoonProps {
  title: string;
  icon: LucideIcon;
  summary: string;
  planned: string[];
}

/** Placeholder for PRD features that are not built yet. Deliberately has no controls. */
export function ComingSoon({ title, icon: Icon, summary, planned }: ComingSoonProps) {
  return (
    <>
      <PageHeader title={title} />
      <Card className="px-6 py-10">
        <div className="mx-auto max-w-lg space-y-4 text-center">
          <div className="mx-auto flex size-10 items-center justify-center rounded-full border bg-muted">
            <Icon className="size-5 text-muted-foreground" aria-hidden />
          </div>
          <div className="space-y-1">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Coming soon
            </p>
            <h2 className="text-base font-semibold">Not available in this release</h2>
            <p className="text-sm text-muted-foreground">{summary}</p>
          </div>
          <ul className="mx-auto max-w-sm space-y-1.5 text-left text-sm text-muted-foreground">
            {planned.map((item) => (
              <li key={item} className="flex gap-2">
                <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </Card>
    </>
  );
}
