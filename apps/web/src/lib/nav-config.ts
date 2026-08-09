import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  Bell,
  CalendarDays,
  CheckSquare,
  Clock,
  FolderOpen,
  HelpCircle,
  Home,
  Megaphone,
  Music,
  Package,
  Palette,
  PenSquare,
  Rocket,
  Settings,
  ShoppingBag,
  Sparkles,
  Wallet,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

// Matches the left-nav information architecture from
// 20_USER_PANEL_SPECIFICATION.md exactly, in the same order.
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: Home },
  { label: "Create Content", href: "/create-content", icon: PenSquare },
  { label: "AI Marketing Manager", href: "/marketing-manager", icon: Sparkles },
  { label: "Campaigns", href: "/campaigns", icon: Megaphone },
  { label: "Calendar", href: "/calendar", icon: CalendarDays },
  { label: "Assets", href: "/assets", icon: FolderOpen },
  { label: "Brand Kit", href: "/brand-kit", icon: Palette },
  { label: "Products", href: "/products", icon: Package },
  { label: "eCommerce Store", href: "/ecommerce", icon: ShoppingBag },
  { label: "Audio Studio", href: "/audio-studio", icon: Music },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "Auto-Pilot", href: "/auto-pilot", icon: Rocket },
  { label: "Approvals", href: "/approvals", icon: CheckSquare },
  { label: "Revisions", href: "/revisions", icon: Clock },
  { label: "Billing", href: "/billing", icon: Wallet },
  { label: "Settings", href: "/settings", icon: Settings },
  { label: "Help", href: "/help", icon: HelpCircle },
];

export const BELL_ICON = Bell;
