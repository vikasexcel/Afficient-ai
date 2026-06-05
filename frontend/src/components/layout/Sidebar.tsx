import { useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Megaphone,
  BookOpen,
  Users,
  PhoneOutgoing,
  BarChart3,
  FileText,
  Stethoscope,
  Settings as SettingsIcon,
  X,
} from "lucide-react";
import { useMe, canAccessWorkspace, canAccessInsights } from "@/store/me";
import { useUI } from "@/store/ui";

type Item = {
  to: string;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
};

const PRIMARY: Item[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone },
  { to: "/playbooks", label: "Playbooks", icon: BookOpen },
  { to: "/leads", label: "Leads", icon: Users },
  { to: "/calls", label: "Calls", icon: PhoneOutgoing },
];

const INSIGHTS: Item[] = [
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/transcripts", label: "Transcripts", icon: FileText },
  { to: "/diagnostics", label: "AMD Diagnostics", icon: Stethoscope },
];

export default function Sidebar() {
  const me = useMe((s) => s.data);
  const workspace = canAccessWorkspace(me?.role);
  const insights = canAccessInsights(me?.role);

  const sidebarOpen = useUI((s) => s.sidebarOpen);
  const closeSidebar = useUI((s) => s.closeSidebar);
  const location = useLocation();

  // Auto-close the mobile drawer when the route changes so navigation feels
  // like a real native drawer rather than leaving the overlay on top.
  useEffect(() => {
    closeSidebar();
  }, [location.pathname, closeSidebar]);

  // Lock body scroll while the mobile drawer is open.
  useEffect(() => {
    if (!sidebarOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [sidebarOpen]);

  // Close on Escape when the mobile drawer is open.
  useEffect(() => {
    if (!sidebarOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") closeSidebar();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sidebarOpen, closeSidebar]);

  const primary = workspace
    ? PRIMARY
    : [{ to: "/dashboard", label: "Dashboard", icon: LayoutDashboard }];

  return (
    <>
      {/* Mobile backdrop. Sits below the drawer, above page content. */}
      <div
        onClick={closeSidebar}
        aria-hidden
        className={[
          "fixed inset-0 z-30 bg-black/60 backdrop-blur-sm transition-opacity lg:hidden",
          sidebarOpen
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none",
        ].join(" ")}
      />

      <aside
        className={[
          // Base shell — same look as before.
          "h-screen bg-[#07070a] border-r border-white/[0.05] flex flex-col",
          // Width: keep the desktop width, full-bleed-ish on mobile but capped.
          "w-[260px] sm:w-[260px] lg:w-[232px]",
          // Mobile: off-canvas drawer that slides in.
          "fixed inset-y-0 left-0 z-40 transition-transform duration-200",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
          // Desktop: static, always visible, no transform.
          "lg:static lg:translate-x-0 lg:z-auto lg:transition-none",
        ].join(" ")}
      >
        <div className="sidebar-brand h-[52px] flex items-center justify-between px-5 border-b border-white/[0.05]">
          <span
            className="text-[13px] font-medium text-white"
            style={{ letterSpacing: "0.2em" }}
          >
            AI<span className="text-violet-300">FF</span>ICIENT
          </span>
          {/* Mobile close affordance. Hidden on desktop. */}
          <button
            type="button"
            onClick={closeSidebar}
            aria-label="Close menu"
            className="lg:hidden text-white/50 hover:text-white p-1 -mr-1 rounded-md"
          >
            <X size={16} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5">
          <SectionLabel>Workspace</SectionLabel>
          <div className="mt-2 space-y-0.5">
            {primary.map((item) => (
              <NavItem key={item.to} {...item} />
            ))}
          </div>

          {insights && (
            <>
              <SectionLabel className="mt-7">Insights</SectionLabel>
              <div className="mt-2 space-y-0.5">
                {INSIGHTS.map((item) => (
                  <NavItem key={item.to} {...item} />
                ))}
              </div>
            </>
          )}
        </nav>

        <div className="p-3 border-t border-white/[0.05] space-y-3">
          <NavItem to="/settings" label="Settings" icon={SettingsIcon} />
        </div>
      </aside>
    </>
  );
}

function SectionLabel({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`px-3 text-[10px] font-medium text-white/25 uppercase ${className}`}
      style={{ letterSpacing: "0.12em" }}
    >
      {children}
    </div>
  );
}

function NavItem({ to, label, icon: Icon }: Item) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        [
          "nav-item flex items-center gap-2.5 h-8 px-3 rounded-[7px] text-[13px] transition-colors",
          isActive
            ? "bg-white/[0.04] text-white"
            : "text-white/50 hover:text-white/85 hover:bg-white/[0.03]",
        ].join(" ")
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            size={14}
            className={isActive ? "text-violet-300" : "text-white/40"}
          />
          {label}
        </>
      )}
    </NavLink>
  );
}
