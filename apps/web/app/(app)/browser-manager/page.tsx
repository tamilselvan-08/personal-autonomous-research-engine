import { Globe } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "Browser Manager" };

export default function BrowserManagerPage() {
  return (
    <ComingSoon
      title="Browser Manager"
      icon={Globe}
      summary="Manage isolated browser profiles for sites you are authorised to access, used only when a page needs a real browser."
      planned={[
        "Profiles bound to specific domains, isolated from each other",
        "Manual sign-in sessions; PARE never handles your passwords",
        "Session-expiry detection and browser worker health",
      ]}
    />
  );
}
