import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen,
  Rocket,
  Users,
  Megaphone,
  BookMarked,
  PhoneOutgoing,
  BarChart3,
  FileText,
  Settings as SettingsIcon,
  Shield,
  Search,
  ExternalLink,
  ChevronRight,
} from "lucide-react";

import AppLayout from "@/components/layout/AppLayout";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Section = {
  id: string;
  title: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  blurb: string;
  body: React.ReactNode;
};

const SECTIONS: Section[] = [
  {
    id: "getting-started",
    title: "Getting started",
    icon: Rocket,
    blurb: "Set up your workspace and place your first AI call in minutes.",
    body: (
      <Body>
        <Step n={1} title="Invite your team">
          Go to <Crumb to="/settings">Settings → Members</Crumb> and add the
          people who'll be running campaigns. Owners and Admins can create and
          launch campaigns; Agents can run calls; Members are view-only.
        </Step>
        <Step n={2} title="Upload your leads">
          Open <Crumb to="/leads">Leads</Crumb> and click <em>Import</em>. Drop
          a CSV with at least <Code>name</Code> and <Code>phone</Code>. Unknown
          columns are preserved as custom fields. Duplicates are auto-detected.
        </Step>
        <Step n={3} title="Pick or build a playbook">
          A playbook tells the AI agent how to talk, qualify, and adapt. Start
          from <Crumb to="/playbooks">Playbooks</Crumb> and choose a framework
          (BANT, MEDDICC, or Custom).
        </Step>
        <Step n={4} title="Launch a campaign">
          From <Crumb to="/campaigns">Campaigns</Crumb> click <em>New
          campaign</em>, pick your playbook + lead list, set business hours,
          then <em>Launch</em>. The agent dials within your calling window.
        </Step>
        <Callout tone="violet">
          Want to dry-run first? Use{" "}
          <Crumb to="/calls">Calls → Browser test room</Crumb> to talk to the
          AI agent through your mic before any real numbers are dialed.
        </Callout>
      </Body>
    ),
  },
  {
    id: "campaigns",
    title: "Campaigns",
    icon: Megaphone,
    blurb: "Configure targeting, scheduling, and calling windows.",
    body: (
      <Body>
        <P>
          A campaign joins a <em>playbook</em> with a <em>lead list</em> and a{" "}
          <em>schedule</em>. The AI agent picks the next lead, dials, follows
          the playbook, qualifies, and writes results back to the transcript
          and analytics views.
        </P>
        <H>Schedule</H>
        <P>
          Pick <em>Start immediately</em> for instant dialing, or set a future
          date/time. The timezone defaults to your browser timezone — change it
          if you're scheduling on behalf of another region.
        </P>
        <H>Business hours</H>
        <P>
          The agent will only place calls inside the configured window on the
          selected weekdays. Enable <em>Skip national holidays</em> to pause
          dialing on observed public holidays in the chosen timezone.
        </P>
        <H>Drafts</H>
        <P>
          You can save a campaign as a draft at any point. Drafts live locally
          in your browser and appear under the Drafts section of the Campaigns
          page until you launch them.
        </P>
      </Body>
    ),
  },
  {
    id: "playbooks",
    title: "Playbooks",
    icon: BookMarked,
    blurb: "Define how the AI agent talks, qualifies, and branches.",
    body: (
      <Body>
        <H>Framework</H>
        <P>
          Pick one of three starting points:
        </P>
        <ul className="space-y-1.5 text-[13px] text-white/70 list-disc pl-5">
          <li>
            <strong className="text-white">BANT</strong> — Budget, Authority,
            Need, Timeline. Best for classic outbound SDR motions.
          </li>
          <li>
            <strong className="text-white">MEDDICC</strong> — Metrics, Economic
            Buyer, Decision Criteria, Decision Process, Identify Pain,
            Champion, Competition. Best for enterprise sales.
          </li>
          <li>
            <strong className="text-white">Custom</strong> — Bring your own
            fields. Start empty and add as many as you need.
          </li>
        </ul>
        <H>Fields</H>
        <P>
          Each field is something the agent should learn during the call. Set
          a <Code>weight</Code> for importance (1–3) and toggle{" "}
          <Code>required</Code> to gate qualification. Add cue patterns
          (keywords or advanced regex) to help detect when a field is answered.
        </P>
        <H>Branches</H>
        <P>
          Smart branching adapts mid-call — switch persona once qualified,
          escalate to a different framework if objections fire, etc. Branches
          run by priority and can be one-shot or repeating.
        </P>
        <H>Versioning</H>
        <P>
          Editing a published playbook creates a new draft version. Click{" "}
          <em>Publish</em> to make the new version live. Running calls
          continue using whichever version they started on.
        </P>
      </Body>
    ),
  },
  {
    id: "leads",
    title: "Leads",
    icon: Users,
    blurb: "Import, segment, and triage your prospect lists.",
    body: (
      <Body>
        <H>Import</H>
        <P>
          CSV imports support up to 5 MB per file, UTF-8 encoded, with one
          header row. Required columns: <Code>name</Code> and <Code>phone</Code>.
          Optional: <Code>email</Code>, <Code>company</Code>,{" "}
          <Code>industry</Code>, <Code>location</Code>, <Code>tags</Code>.
          Any other columns are stored as custom fields.
        </P>
        <H>Segmentation</H>
        <P>
          During import you can apply shared metadata (industry, location,
          tags, ad-hoc custom fields) to every row. Per-row CSV values always
          win over these defaults.
        </P>
        <H>Lead lists</H>
        <P>
          Each import lands in a <em>lead list</em>. Reuse an existing list
          or create a new one. Campaigns target one lead list at a time.
        </P>
        <H>Status</H>
        <P>
          Leads move through <em>New → Contacted → Qualified → Converted</em>{" "}
          (or <em>Lost</em>). The agent updates status automatically based on
          call outcomes; you can also override it manually.
        </P>
      </Body>
    ),
  },
  {
    id: "calls",
    title: "Calls",
    icon: PhoneOutgoing,
    blurb: "Browser test rooms and real-world phone dialer.",
    body: (
      <Body>
        <H>Browser test room</H>
        <P>
          Join a LiveKit audio room from your browser to talk to the AI agent
          end-to-end without dialing a real number. Useful for QA-ing a
          playbook before launching a campaign.
        </P>
        <H>Phone dialer</H>
        <P>
          Place real PSTN calls through Twilio. Enter a destination in E.164
          format (e.g. <Code>+14155551234</Code>), pick a playbook, and click{" "}
          <em>Place call</em>. The backend mints a LiveKit room, bridges the
          carrier audio over SIP, and drops the AI agent in.
        </P>
        <H>Live transcribe</H>
        <P>
          The <em>Live transcribe</em> panel pipes your mic into Deepgram for
          a quick speech-to-text smoke check — handy for verifying audio
          before you commit to a longer call.
        </P>
        <Callout tone="amber">
          Real audio bridging requires <Code>LIVEKIT_SIP_URI</Code> plus a SIP
          trunk configured in LiveKit Cloud. Without it, calls will queue but
          the agent won't hear the lead.
        </Callout>
      </Body>
    ),
  },
  {
    id: "analytics",
    title: "Analytics",
    icon: BarChart3,
    blurb: "Track call volume, conversion funnel, and team performance.",
    body: (
      <Body>
        <P>
          The <Crumb to="/analytics">Analytics</Crumb> page shows KPIs (calls,
          qualified leads, avg. talk time, new contacts), daily call volume, a
          conversion funnel, and top-performing agents and campaigns. Use the
          range selector to switch between 7-, 30-, and 90-day windows.
        </P>
        <H>Conversion funnel</H>
        <P>
          Each step shows raw counts and percentage of the top of the funnel:
        </P>
        <ul className="space-y-1.5 text-[13px] text-white/70 list-disc pl-5">
          <li><strong className="text-white">Dialed</strong> — total outbound attempts.</li>
          <li><strong className="text-white">Connected</strong> — calls that reached a human.</li>
          <li><strong className="text-white">Qualified</strong> — leads that passed playbook criteria.</li>
          <li><strong className="text-white">Converted</strong> — meetings booked or sales closed.</li>
        </ul>
      </Body>
    ),
  },
  {
    id: "transcripts",
    title: "Transcripts",
    icon: FileText,
    blurb: "Review call transcripts and GPT-4o summaries.",
    body: (
      <Body>
        <P>
          Every AI call produces a turn-by-turn transcript with timestamps,
          latency, and token counts. The detail view lets you:
        </P>
        <ul className="space-y-1.5 text-[13px] text-white/70 list-disc pl-5">
          <li>Read the full assistant/user exchange inline.</li>
          <li>
            <em>Finalize</em> a call to generate (or regenerate) the AI summary
            and qualification snapshot.
          </li>
          <li>Export the full payload as JSON for downstream tooling.</li>
          <li>Copy the summary to the clipboard for quick sharing.</li>
        </ul>
      </Body>
    ),
  },
  {
    id: "settings",
    title: "Settings",
    icon: SettingsIcon,
    blurb: "Manage organization, members, profile, and appearance.",
    body: (
      <Body>
        <H>Members</H>
        <P>
          Invite teammates with a role (Owner, Admin, Agent, Member). Owners
          can transfer ownership and delete the organization. Admins can
          manage everyone below Owner. Roles are enforced both in the UI and
          on the backend.
        </P>
        <H>Organization</H>
        <P>
          Rename your workspace, transfer ownership, or permanently delete the
          organization. Deletion requires typing the org name to confirm — it
          can't be undone.
        </P>
        <H>Appearance</H>
        <P>
          Switch between Dark, Light, and System themes. Choose Comfortable or
          Compact density to tighten spacing across the app.
        </P>
        <H>Security</H>
        <P>
          Reset your own password or another member's. Active sessions and
          API tokens can be revoked from this tab.
        </P>
      </Body>
    ),
  },
  {
    id: "roles",
    title: "Roles & permissions",
    icon: Shield,
    blurb: "Who can do what across the workspace.",
    body: (
      <Body>
        <div className="overflow-x-auto rounded-[10px] border border-white/[0.07] bg-white/[0.02]">
          <table className="w-full min-w-[520px] text-[13px]">
            <thead>
              <tr className="border-b border-white/[0.06] text-[11px] uppercase tracking-wider text-white/45">
                <th className="text-left px-4 py-2.5">Capability</th>
                <th className="text-center px-3 py-2.5">Owner</th>
                <th className="text-center px-3 py-2.5">Admin</th>
                <th className="text-center px-3 py-2.5">Agent</th>
                <th className="text-center px-3 py-2.5">Member</th>
              </tr>
            </thead>
            <tbody className="text-white/75">
              <PermRow cap="View dashboard" o a g m />
              <PermRow cap="Run calls" o a g />
              <PermRow cap="Create / edit playbooks" o a />
              <PermRow cap="Launch campaigns" o a />
              <PermRow cap="Manage members" o a />
              <PermRow cap="Rename / delete org" o />
              <PermRow cap="Transfer ownership" o />
            </tbody>
          </table>
        </div>
      </Body>
    ),
  },
  {
    id: "faq",
    title: "FAQ",
    icon: BookOpen,
    blurb: "Quick answers to common questions.",
    body: (
      <Body>
        <Q q="Why don't I see the Calls or Campaigns pages?">
          Your role doesn't have workspace access. Ask an Admin to upgrade you
          to <em>Agent</em> or higher.
        </Q>
        <Q q="My CSV import says rows are invalid — why?">
          The most common causes are missing <Code>name</Code> or{" "}
          <Code>phone</Code>, badly formatted phone numbers (E.164 is safest),
          and non-UTF-8 encoded files. Use the <em>Export invalid</em> button
          in the import dialog to download just the rejected rows with their
          error messages.
        </Q>
        <Q q="Can I edit a playbook while a campaign is running?">
          Yes. Edits create a new draft version. Live calls keep using the
          version they started on. New calls after you click <em>Publish</em>{" "}
          will pick up the new version.
        </Q>
        <Q q="How do I cancel an in-flight phone call?">
          From <Crumb to="/calls">Calls → Phone dialer → Recent calls</Crumb>,
          click <em>Cancel</em> on any non-terminal call. Failed, busy, and
          no-answer calls have a <em>Retry</em> button.
        </Q>
        <Q q="Where do I report a bug?">
          Email <Code>support@aifficient.ai</Code> or ping us in your shared
          Slack channel. Include the call ID (visible in the URL or Transcripts
          page) so we can pull the full session log.
        </Q>
      </Body>
    ),
  },
];

export default function Documentation() {
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string>(SECTIONS[0].id);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return SECTIONS;
    return SECTIONS.filter(
      (s) =>
        s.title.toLowerCase().includes(q) || s.blurb.toLowerCase().includes(q)
    );
  }, [query]);

  function jumpTo(id: string) {
    setActiveId(id);
    const el = document.getElementById(`doc-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  return (
    <AppLayout>
      <div className="space-y-6 max-w-6xl">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-medium text-white">
              Documentation
            </h1>
            <p className="text-[13px] text-white/40 mt-1 max-w-2xl">
              Everything you need to know about running Tellaigent — from your
              first campaign to advanced playbook branching.
            </p>
          </div>
          <a
            href="https://aifficient.ai/docs"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-[12px] text-white/60 hover:text-white border border-white/[0.08] hover:border-white/[0.16] bg-white/[0.03] hover:bg-white/[0.05] rounded-[8px] px-3 h-8 transition-colors self-start sm:self-auto"
          >
            <ExternalLink size={12} />
            Full docs site
          </a>
        </div>

        {/* Body */}
        <div className="grid grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)] gap-4 lg:gap-6 items-start">
          {/* Sidebar nav */}
          <aside className="lg:sticky lg:top-2 space-y-3">
            <div className="relative">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/35"
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search topics"
                className="pl-8 h-9 bg-white/[0.03] border-white/[0.08] text-[13px]"
              />
            </div>

            <nav className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-1.5 max-h-[260px] lg:max-h-none overflow-y-auto">
              {filtered.length === 0 ? (
                <div className="text-[12px] text-white/40 px-3 py-4 text-center">
                  No topics match "{query}".
                </div>
              ) : (
                filtered.map((s) => {
                  const Icon = s.icon;
                  const active = activeId === s.id;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => jumpTo(s.id)}
                      className={cn(
                        "w-full flex items-center gap-2.5 px-2.5 h-8 rounded-[7px] text-[12.5px] transition-colors text-left",
                        active
                          ? "bg-violet-500/10 text-white"
                          : "text-white/55 hover:text-white/85 hover:bg-white/[0.03]"
                      )}
                    >
                      <Icon
                        size={13}
                        className={active ? "text-violet-300" : "text-white/40"}
                      />
                      <span className="truncate">{s.title}</span>
                    </button>
                  );
                })
              )}
            </nav>
          </aside>

          {/* Article column */}
          <article className="space-y-6">
            {(filtered.length === 0 ? SECTIONS : filtered).map((s) => {
              const Icon = s.icon;
              return (
                <section
                  key={s.id}
                  id={`doc-${s.id}`}
                  className="rounded-[12px] border border-white/[0.07] bg-white/[0.02] p-5 sm:p-6 scroll-mt-4"
                >
                  <header className="flex items-start gap-3 mb-4">
                    <span className="inline-flex items-center justify-center w-9 h-9 rounded-[9px] bg-violet-500/10 border border-violet-500/25 text-violet-300 shrink-0">
                      <Icon size={15} />
                    </span>
                    <div className="min-w-0">
                      <h2 className="text-[16px] sm:text-[17px] font-medium text-white">
                        {s.title}
                      </h2>
                      <p className="text-[12.5px] text-white/45 mt-0.5">
                        {s.blurb}
                      </p>
                    </div>
                  </header>
                  {s.body}
                </section>
              );
            })}

            {/* Footer */}
            <div className="rounded-[12px] border border-violet-500/20 bg-violet-500/[0.04] p-5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <div className="text-[13px] text-white font-medium">
                  Still stuck?
                </div>
                <p className="text-[12px] text-white/55 mt-0.5">
                  Email <Code>support@aifficient.ai</Code> and we'll get back
                  within one business day.
                </p>
              </div>
              <a
                href="mailto:support@aifficient.ai"
                className="inline-flex items-center gap-1.5 text-[12px] text-violet-200 hover:text-white bg-violet-600 hover:bg-violet-500 rounded-[8px] px-3.5 h-8 font-medium transition-colors self-start sm:self-auto"
              >
                Contact support
                <ChevronRight size={12} />
              </a>
            </div>
          </article>
        </div>
      </div>
    </AppLayout>
  );
}

/* -------------------------------------------------------------------------- */
/* Body primitives                                                            */
/* -------------------------------------------------------------------------- */

function Body({ children }: { children: React.ReactNode }) {
  return <div className="space-y-3 text-[13px] text-white/75 leading-relaxed">{children}</div>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="leading-relaxed">{children}</p>;
}

function H({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[12px] font-medium text-white/85 uppercase tracking-wider mt-2">
      {children}
    </h3>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="px-1.5 py-0.5 rounded-[5px] bg-white/[0.06] border border-white/[0.08] text-violet-200 font-mono text-[12px]">
      {children}
    </code>
  );
}

function Crumb({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="text-violet-300 hover:text-violet-200 underline-offset-2 hover:underline"
    >
      {children}
    </Link>
  );
}

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-3">
      <span className="shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-full bg-violet-500/15 border border-violet-500/30 text-[11px] font-semibold text-violet-200">
        {n}
      </span>
      <div className="min-w-0">
        <div className="text-[13px] text-white font-medium">{title}</div>
        <p className="text-[12.5px] text-white/65 mt-0.5 leading-relaxed">
          {children}
        </p>
      </div>
    </div>
  );
}

function Callout({
  tone,
  children,
}: {
  tone: "violet" | "amber";
  children: React.ReactNode;
}) {
  const toneClass =
    tone === "amber"
      ? "border-amber-500/25 bg-amber-500/[0.06] text-amber-100/90"
      : "border-violet-500/25 bg-violet-500/[0.06] text-violet-100/90";
  return (
    <div
      className={cn(
        "rounded-[10px] border px-3.5 py-2.5 text-[12.5px] leading-relaxed",
        toneClass
      )}
    >
      {children}
    </div>
  );
}

function Q({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <div className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] px-3.5 py-3">
      <div className="text-[13px] text-white font-medium">{q}</div>
      <div className="text-[12.5px] text-white/65 mt-1 leading-relaxed">
        {children}
      </div>
    </div>
  );
}

function PermRow({
  cap,
  o,
  a,
  g,
  m,
}: {
  cap: string;
  o?: boolean;
  a?: boolean;
  g?: boolean;
  m?: boolean;
}) {
  return (
    <tr className="border-b border-white/[0.04] last:border-b-0">
      <td className="px-4 py-2.5 text-white/80">{cap}</td>
      <Cell on={o} />
      <Cell on={a} />
      <Cell on={g} />
      <Cell on={m} />
    </tr>
  );
}

function Cell({ on }: { on?: boolean }) {
  return (
    <td className="text-center px-3 py-2.5">
      {on ? (
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400" />
      ) : (
        <span className="text-white/20">—</span>
      )}
    </td>
  );
}
