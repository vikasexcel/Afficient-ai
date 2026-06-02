// import {
//   Button,
// } from "@/components/ui/button";

// import {
//   useAuth,
// } from "@/store/auth";

// export default function Dashboard() {
//   const logout =
//     useAuth(
//       (s) =>
//         s.logout
//     );

//   return (
//     <div
//       className="
//         min-h-screen
//         bg-black
//         text-white
//       "
//     >
//       <div
//         className="
//           max-w-7xl
//           mx-auto
//           p-10
//         "
//       >
//         <h1
//           className="
//             text-5xl
//             font-bold
//           "
//         >
//           Dashboard
//         </h1>

//         <Button
//           className="
//             mt-6
//           "
//           onClick={
//             logout
//           }
//         >
//           Logout
//         </Button>
//       </div>
//     </div>
//   );
// }


// import AppLayout
// from "@/components/layout/AppLayout"

// export default function Dashboard(){

// return(

// <AppLayout>

// <h1
// className="
// text-4xl
// font-bold
// "
// >

// Dashboard

// </h1>

// </AppLayout>

// )

// }


import AppLayout from "@/components/layout/AppLayout";
import { Link } from "react-router-dom";

const metrics = [
  {
    label: "Calls made",
    value: "284",
    delta: "+12%",
    positive: true,
    sub: "vs yesterday",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.64 12 19.79 19.79 0 0 1 1.56 3.44 2 2 0 0 1 3.54 1.25h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.81a16 16 0 0 0 5.55 5.55l.88-.88a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 21 16z" />
        <path d="M14.05 3a9 9 0 0 1 8 7.94M14.05 7A5 5 0 0 1 18 11" />
      </svg>
    ),
  },
  {
    label: "Connected",
    value: "71%",
    delta: "+3%",
    positive: true,
    sub: "connection rate",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8h1a4 4 0 0 1 0 8h-1" />
        <path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z" />
        <line x1="6" y1="1" x2="6" y2="4" />
        <line x1="10" y1="1" x2="10" y2="4" />
        <line x1="14" y1="1" x2="14" y2="4" />
      </svg>
    ),
  },
  {
    label: "Meetings booked",
    value: "34",
    delta: "+8%",
    positive: true,
    sub: "vs yesterday",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <path d="m9 16 2 2 4-4" />
      </svg>
    ),
  },
  {
    label: "Cost per meeting",
    value: "$24",
    delta: "+$2",
    positive: false,
    sub: "vs yesterday",
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 6v2m0 8v2M9.5 9.5A2.5 2.5 0 0 1 12 8h.5a2.5 2.5 0 0 1 0 5h-1a2.5 2.5 0 0 0 0 5h.5a2.5 2.5 0 0 0 2.5-2.5" />
      </svg>
    ),
  },
];

const campaigns = [
  { name: "Q2 SaaS Outbound", status: "active", leads: 420, called: 284, meetings: 34, rate: "12%" },
  { name: "Enterprise FS Pilot", status: "paused", leads: 180, called: 92, meetings: 9, rate: "10%" },
  { name: "SMB Spring Push", status: "ended", leads: 640, called: 640, meetings: 58, rate: "9%" },
];

const statusStyles: Record<string, { dot: string; text: string; bg: string; border: string }> = {
  active: { dot: "#4ade80", text: "#4ade80", bg: "rgba(74,222,128,0.08)", border: "rgba(74,222,128,0.2)" },
  paused: { dot: "#fbbf24", text: "#fbbf24", bg: "rgba(251,191,36,0.08)", border: "rgba(251,191,36,0.2)" },
  ended:  { dot: "rgba(255,255,255,0.25)", text: "rgba(255,255,255,0.35)", bg: "rgba(255,255,255,0.04)", border: "rgba(255,255,255,0.1)" },
};

const today = new Date().toLocaleDateString("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

export default function Dashboard() {
  return (
    <AppLayout>
      <div className="space-y-6 sm:space-y-8">

        {/* Page header */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div>
            <h1
              className="text-[20px] sm:text-[22px] font-semibold text-white"
              style={{ fontFamily: "'DM Serif Display', serif" }}
            >
              Dashboard
            </h1>
            <p className="text-[12px] sm:text-[13px] text-white/35 mt-0.5">
              {today}
            </p>
          </div>
          <Link to="/campaigns" className="shrink-0">
            <button className="flex items-center gap-1.5 bg-violet-600 hover:bg-violet-500 transition-colors text-white text-[12px] font-semibold px-3.5 py-2 rounded-[8px] whitespace-nowrap">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              New campaign
            </button>
          </Link>
        </div>

        {/* Metric cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {metrics.map((m) => (
            <div
              key={m.label}
              className="bg-white/[0.03] border border-white/[0.07] rounded-[10px] p-4 hover:bg-white/[0.05] transition-colors"
            >
              <div className="flex items-center gap-1.5 text-white/40 mb-3">
                {m.icon}
                <span className="text-[11px] font-medium tracking-wide">{m.label}</span>
              </div>
              <div
                className="text-[26px] font-semibold text-white leading-none mb-2"
                style={{ fontFamily: "'DM Mono', monospace" }}
              >
                {m.value}
              </div>
              <div className="flex items-center gap-1.5">
                <span
                  className="text-[11px] font-medium px-1.5 py-0.5 rounded-[4px]"
                  style={{
                    color: m.positive ? "#4ade80" : "#f87171",
                    background: m.positive ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)",
                  }}
                >
                  {m.delta}
                </span>
                <span className="text-[11px] text-white/25">{m.sub}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Funnel row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 bg-white/[0.02] border border-white/[0.06] rounded-[10px] overflow-hidden">
          {[
            { label: "Leads uploaded", val: 1240, pct: 100 },
            { label: "Contacted", val: 1016, pct: 82 },
            { label: "Qualified", val: 284, pct: 23 },
            { label: "Meetings booked", val: 101, pct: 8 },
          ].map((s, i) => {
            // Mobile 2x2 grid: only items in the first row need a bottom
            // divider, and odd-indexed items are rightmost so they skip the
            // right border. Desktop is a single 4-col row — every item gets a
            // right border except the last.
            const mobileBorderB = i < 2 ? "border-b lg:border-b-0" : "";
            const mobileBorderR = i % 2 === 0 ? "border-r" : "lg:border-r";
            const desktopLast = i === 3 ? "lg:border-r-0" : "";
            return (
            <div
              key={s.label}
              className={`px-4 sm:px-5 py-4 border-white/[0.06] ${mobileBorderB} ${mobileBorderR} ${desktopLast}`}
            >
              <div className="text-[11px] text-white/30 mb-2">{s.label}</div>
              <div
                className="text-[20px] font-semibold text-white mb-2"
                style={{ fontFamily: "'DM Mono', monospace" }}
              >
                {s.val.toLocaleString()}
              </div>
              {/* Bar */}
              <div className="h-1 bg-white/[0.06] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${s.pct}%`,
                    background: i === 0 ? "#6d28d9" : i === 1 ? "#7c3aed" : i === 2 ? "#8b5cf6" : "#a78bfa",
                  }}
                />
              </div>
              <div className="text-[10px] text-white/20 mt-1.5">{s.pct}% of total</div>
            </div>
            );
          })}
        </div>

        {/* Campaigns table */}
        <div>
          <div className="flex items-center justify-between mb-3.5">
            <h2 className="text-[14px] font-semibold text-white/80">Active campaigns</h2>
            <Link
              to="/campaigns"
              className="text-[12px] text-violet-400 hover:text-violet-300 transition-colors"
            >
              View all →
            </Link>
          </div>

          <div className="bg-white/[0.02] border border-white/[0.07] rounded-[10px] overflow-hidden">
            <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-[13px] border-collapse">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  {["Campaign", "Status", "Leads", "Called", "Meetings", "Conv. rate"].map((h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 text-[11px] font-medium text-white/25 tracking-wide whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => {
                  const s = statusStyles[c.status];
                  const pct = Math.round((c.called / c.leads) * 100);
                  return (
                    <tr
                      key={c.name}
                      className="border-b border-white/[0.04] last:border-b-0 hover:bg-white/[0.02] transition-colors cursor-pointer group"
                    >
                      <td className="px-4 py-3.5 font-medium text-white/90 group-hover:text-white transition-colors">
                        {c.name}
                      </td>
                      <td className="px-4 py-3.5">
                        <span
                          className="inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full"
                          style={{ color: s.text, background: s.bg, border: `0.5px solid ${s.border}` }}
                        >
                          <span
                            className="w-[5px] h-[5px] rounded-full flex-shrink-0"
                            style={{ background: s.dot }}
                          />
                          {c.status.charAt(0).toUpperCase() + c.status.slice(1)}
                        </span>
                      </td>
                      <td
                        className="px-4 py-3.5 text-white/50"
                        style={{ fontFamily: "'DM Mono', monospace" }}
                      >
                        {c.leads}
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1 bg-white/[0.08] rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full bg-violet-500"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span
                            className="text-white/50"
                            style={{ fontFamily: "'DM Mono', monospace" }}
                          >
                            {c.called}
                          </span>
                        </div>
                      </td>
                      <td
                        className="px-4 py-3.5 text-white/50"
                        style={{ fontFamily: "'DM Mono', monospace" }}
                      >
                        {c.meetings}
                      </td>
                      <td
                        className="px-4 py-3.5 font-medium"
                        style={{
                          fontFamily: "'DM Mono', monospace",
                          color: parseInt(c.rate) >= 10 ? "#4ade80" : "rgba(255,255,255,0.5)",
                        }}
                      >
                        {c.rate}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </div>
        </div>

      </div>
    </AppLayout>
  );
}