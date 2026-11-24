import {
  Bot,
  FolderKanban,
  Globe,
  History,
  LayoutDashboard,
  Search,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  comingSoon?: boolean;
}

export const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: "Workspace",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/research", label: "Research", icon: Search },
      { href: "/projects", label: "Projects", icon: FolderKanban },
      { href: "/history", label: "History", icon: History },
    ],
  },
  {
    label: "Configuration",
    items: [
      { href: "/ai-providers", label: "AI Providers", icon: Bot },
      { href: "/browser-manager", label: "Browser Manager", icon: Globe, comingSoon: true },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
