/*
import {
  Home,
  Layers,
  Settings,
} from "lucide-react";

import { Link } from "react-router-dom";

export default function Sidebar() {
  return (
    <div
      className="
        w-[260px]
        border-r
        h-screen
        bg-zinc-950
        p-6
      "
    >
      <h1
        className="
          text-white
          font-bold
          text-xl
          mb-8
        "
      >
        AIFFICIENT
      </h1>

      <nav
        className="
          space-y-3
        "
      >
        <Link to="/dashboard">
          <div
            className="
              flex
              gap-3
              text-zinc-300
            "
          >
            <Home />
            Dashboard
          </div>
        </Link>

        <Link to="/campaigns">
          <div
            className="
              flex
              gap-3
              text-zinc-300
            "
          >
            <Layers />
            Campaigns
          </div>
        </Link>

        <Link to="/settings">
          <div
            className="
              flex
              gap-3
              text-zinc-300
            "
          >
            <Settings />
            Settings
          </div>
        </Link>
      </nav>
    </div>
  );
}

*/ 



import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Megaphone,
  BookOpen,
  Users,
  PhoneOutgoing,
  BarChart3,
  FileText,
  Settings as SettingsIcon,
} from "lucide-react";
import { useMe, canAccessWorkspace, canAccessInsights } from "@/store/me";

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
];

export default function Sidebar() {
  const me = useMe((s) => s.data);
  const workspace = canAccessWorkspace(me?.role);
  const insights = canAccessInsights(me?.role);

  const primary = workspace
    ? PRIMARY
    : [{ to: "/dashboard", label: "Dashboard", icon: LayoutDashboard }];

  return (
    <aside className="w-[232px] h-screen bg-[#07070a] border-r border-white/[0.05] flex flex-col">
      <div className="sidebar-brand h-[52px] flex items-center px-5 border-b border-white/[0.05]">
        <span
          className="text-[13px] font-medium text-white"
          style={{ letterSpacing: "0.2em" }}
        >
          AI<span className="text-violet-300">FF</span>ICIENT
        </span>
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
        {/* <div className="rounded-[10px] border border-violet-500/20 bg-violet-500/[0.06] p-3">
          <div className="flex items-center gap-1.5">
            <Sparkles size={12} className="text-violet-300" />
            <span className="text-[11px] font-medium text-violet-200">
              Upgrade to Pro
            </span>
          </div>
          <p className="mt-1 text-[11px] text-white/40 leading-snug">
            Unlock unlimited calls and live coaching.
          </p>
          <button className="mt-2.5 w-full h-7 rounded-[7px] bg-violet-600 hover:bg-violet-500 text-white text-[11px] font-medium transition-colors">
            Upgrade
          </button>
        </div> */}

        <NavItem to="/settings" label="Settings" icon={SettingsIcon} />
      </div>
    </aside>
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
