// import {
//   Avatar,
//   AvatarFallback,
// } from "@/components/ui/avatar";

// import { Button } from "@/components/ui/button";

// import { useNavigate } from "react-router-dom";

// import { logout } from "@/services/auth";

// import { useAuth } from "@/store/auth";

// export default function Header() {
//   const nav = useNavigate();

//   const clear = useAuth((s) => s.logout);

//   const refresh = useAuth((s) => s.refreshToken);

//   async function signout() {
//     try {
//       if (refresh) {
//         await logout(refresh);
//       }
//     } finally {
//       clear();
//       nav("/login");
//     }
//   }

//   return (
//     <header
//       className="
//         h-20
//         border-b
//         flex
//         justify-end
//         items-center
//         gap-4
//         px-8
//       "
//     >
//       <Avatar>
//         <AvatarFallback>
//           NK
//         </AvatarFallback>
//       </Avatar>

//       <Button
//         variant="outline"
//         onClick={signout}
//       >
//         Logout
//       </Button>
//     </header>
//   );
// }


import { useNavigate, useLocation } from "react-router-dom";
import { useState } from "react";
import { logout } from "@/services/auth";
import { useAuth } from "@/store/auth";
import { useMe } from "@/store/me";

const routeLabels: Record<string, string> = {
  "/dashboard":  "Dashboard",
  "/campaigns":  "Campaigns",
  "/leads":      "Leads",
  "/calls":      "Calls",
  "/analytics":  "Analytics",
  "/transcripts":"Transcripts",
  "/settings":   "Settings",
};

function initials(name?: string) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

function shortName(name?: string) {
  if (!name) return "—";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0];
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

function titleCase(s?: string | null) {
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function Header() {
  const nav      = useNavigate();
  const location = useLocation();
  const clear    = useAuth((s) => s.logout);
  const refresh  = useAuth((s) => s.refreshToken);
  const user     = useMe((s) => s.data);
  const resetMe  = useMe((s) => s.reset);

  const [menuOpen, setMenuOpen]   = useState(false);
  const [signing,  setSigning]    = useState(false);

  const pageLabel = routeLabels[location.pathname] ?? "Aifficient";

  async function signout() {
    setSigning(true);
    try {
      if (refresh) await logout(refresh);
    } finally {
      clear();
      resetMe();
      nav("/login");
    }
  }

  return (
    <header className="h-[52px] border-b border-white/[0.05] flex items-center justify-between px-6 bg-[#07070a] relative z-10">

      {/* Left — breadcrumb */}
      <div className="flex items-center gap-2 text-[13px]">
        <span className="text-white/25">{user?.organization?.name ?? "Aifficient"}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-white/15">
          <polyline points="9 18 15 12 9 6" />
        </svg>
        <span className="text-white/80 font-medium">{pageLabel}</span>
      </div>

      {/* Right — actions */}
      <div className="flex items-center gap-2">

        {/* Search */}
        <button
          aria-label="Search"
          className="w-8 h-8 flex items-center justify-center rounded-[7px] border border-white/[0.08] text-white/35 hover:text-white/70 hover:border-white/[0.15] transition-all"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>

        {/* Notifications */}
        <button
          aria-label="Notifications"
          className="relative w-8 h-8 flex items-center justify-center rounded-[7px] border border-white/[0.08] text-white/35 hover:text-white/70 hover:border-white/[0.15] transition-all"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          {/* Unread dot */}
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-violet-400" />
        </button>

        {/* Divider */}
        <div className="w-px h-5 bg-white/[0.07] mx-1" />

        {/* Avatar menu */}
        <div className="relative">
          <button
            onClick={() => setMenuOpen((o) => !o)}
            className="flex items-center gap-2 px-2 py-1 rounded-[8px] hover:bg-white/[0.05] transition-colors"
          >
            {/* Avatar */}
            <div className="w-7 h-7 rounded-full bg-violet-500/20 flex items-center justify-center text-[11px] font-semibold text-violet-300 flex-shrink-0">
              {initials(user?.full_name)}
            </div>
            <div className="text-left hidden sm:block">
              <div className="text-[12px] font-medium text-white/80 leading-none">
                {shortName(user?.full_name)}
              </div>
              <div className="text-[10px] text-white/30 leading-none mt-0.5">
                {titleCase(user?.role)}
              </div>
            </div>
            <svg
              width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
              className={`text-white/25 transition-transform ${menuOpen ? "rotate-180" : ""}`}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          {/* Dropdown */}
          {menuOpen && (
            <>
              {/* Backdrop */}
              <div
                className="fixed inset-0 z-10"
                onClick={() => setMenuOpen(false)}
              />

              <div className="absolute right-0 top-full mt-2 w-[180px] bg-[#111114] border border-white/[0.08] rounded-[10px] shadow-xl z-20 overflow-hidden py-1">

                {/* User info row */}
                <div className="px-3 py-2.5 border-b border-white/[0.06]">
                  <div className="text-[12px] font-medium text-white/80">
                    {user?.full_name ?? "Loading…"}
                  </div>
                  <div className="text-[11px] text-white/30 truncate">
                    {user?.email ?? ""}
                  </div>
                </div>

                {[
                  {
                    label: "Settings",
                    onClick: () => { setMenuOpen(false); nav("/settings"); },
                    icon: (
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="3" />
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                      </svg>
                    ),
                  },
                  {
                    label: "Documentation",
                    onClick: () => setMenuOpen(false),
                    icon: (
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="16" y1="13" x2="8" y2="13" />
                        <line x1="16" y1="17" x2="8" y2="17" />
                        <polyline points="10 9 9 9 8 9" />
                      </svg>
                    ),
                  },
                ].map((item) => (
                  <button
                    key={item.label}
                    onClick={item.onClick}
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-[12px] text-white/50 hover:text-white/80 hover:bg-white/[0.04] transition-colors text-left"
                  >
                    <span className="text-white/30">{item.icon}</span>
                    {item.label}
                  </button>
                ))}

                {/* Divider */}
                <div className="h-px bg-white/[0.06] my-1" />

                {/* Logout */}
                <button
                  onClick={signout}
                  disabled={signing}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-[12px] text-red-400/70 hover:text-red-400 hover:bg-red-500/[0.06] transition-colors text-left disabled:opacity-50"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <polyline points="16 17 21 12 16 7" />
                    <line x1="21" y1="12" x2="9" y2="12" />
                  </svg>
                  {signing ? "Signing out…" : "Sign out"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}