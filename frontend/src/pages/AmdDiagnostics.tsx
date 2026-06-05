import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import { Button } from "@/components/ui/button";
import { formatAuthError } from "@/services/auth";
import { getAmdDiagnostics, type AmdDiagnostics } from "@/services/telephony";

export default function AmdDiagnostics() {
  const [data, setData] = useState<AmdDiagnostics | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getAmdDiagnostics());
    } catch (err) {
      toast.error(formatAuthError(err) || "Failed to load diagnostics");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppLayout>
      <div className="max-w-4xl space-y-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-medium text-white">
              AMD Diagnostics
            </h1>
            <p className="text-[13px] text-white/40 mt-1">
              Runtime status of Answering Machine Detection &amp; voicemail drop
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={load}
            disabled={loading}
            className="border-white/[0.08] bg-white/[0.03] text-white/80 hover:bg-white/[0.06]"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            Refresh
          </Button>
        </div>

        {loading && !data ? (
          <div className="flex items-center justify-center py-20 text-white/45">
            <Loader2 size={18} className="animate-spin mr-2" />
            Loading diagnostics…
          </div>
        ) : data ? (
          <>
            <ReadinessBanner ready={data.real_voicemail_call_ready} />

            {data.blockers.length > 0 && (
              <section className="rounded-[12px] border border-amber-500/20 bg-amber-500/[0.05] p-4">
                <div className="flex items-center gap-2 text-[13px] text-amber-200 font-medium">
                  <AlertTriangle size={14} />
                  Blockers ({data.blockers.length})
                </div>
                <ul className="mt-2 space-y-1.5">
                  {data.blockers.map((b, i) => (
                    <li
                      key={i}
                      className="text-[12px] text-amber-100/80 flex gap-2"
                    >
                      <span className="text-amber-400/70 shrink-0">•</span>
                      {b}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <Panel title="Call routing">
              <BoolRow
                label="Twilio path active (runs AMD)"
                value={data.twilio_path_active}
              />
              <BoolRow
                label="LiveKit SIP path active (no AMD)"
                value={data.livekit_path_active}
                neutral
              />
              <BoolRow
                label="Campaign telephony dialing enabled"
                value={data.campaign_telephony_dialing_enabled}
              />
              <BoolRow
                label="AMD enabled (global)"
                value={data.amd_enabled_global}
              />
              <KvRow label="AMD mode" value={data.amd_mode} />
              <KvRow
                label="AMD timeout"
                value={`${data.amd_timeout_seconds}s`}
              />
            </Panel>

            <Panel title="Twilio">
              <BoolRow label="Configured" value={data.twilio.configured} />
              <BoolRow
                label="Dummy credentials"
                value={data.twilio.dummy_credentials}
                invert
              />
              <KvRow label="Auth mode" value={data.twilio.auth_mode ?? "—"} />
              <KvRow
                label="Public base URL"
                value={data.twilio.public_base_url ?? "—"}
                mono
              />
              <KvRow
                label="Phone number"
                value={data.twilio.phone_number ?? "—"}
                mono
              />
              <BoolRow
                label="Signature validation"
                value={data.twilio.signature_validation}
              />
              <BoolRow
                label="Can validate signatures"
                value={data.twilio.can_validate_signatures}
              />
            </Panel>

            <Panel title="LiveKit SIP">
              <KvRow
                label="SIP URI"
                value={data.livekit_sip.sip_uri ?? "—"}
                mono
              />
              <KvRow
                label="Outbound trunk id"
                value={data.livekit_sip.outbound_trunk_id ?? "—"}
                mono
              />
            </Panel>

            <Panel title="Voicemail storage / validation">
              <BoolRow
                label="Require public URL"
                value={data.voicemail.require_public_url}
              />
              <BoolRow
                label="URL network check"
                value={data.voicemail.url_network_check}
                neutral
              />
              <KvRow
                label="Public route"
                value={data.voicemail.public_route}
                mono
              />
              <KvRow
                label="Allowed formats"
                value={data.voicemail.allowed_formats}
              />
              <KvRow
                label="Max upload size"
                value={`${(data.voicemail.max_bytes / (1024 * 1024)).toFixed(
                  1
                )} MB`}
              />
            </Panel>

            <Panel title="Voicemail config status (your org)">
              <KvRow
                label="Campaigns configured"
                value={String(
                  data.voicemail_config_status.campaigns_configured
                )}
              />
              <KvRow
                label="Campaigns enabled"
                value={String(data.voicemail_config_status.campaigns_enabled)}
              />
              <KvRow
                label="With recording"
                value={String(
                  data.voicemail_config_status.campaigns_with_recording
                )}
              />
              <KvRow
                label="Retry on voicemail"
                value={String(
                  data.voicemail_config_status.campaigns_retry_on_voicemail
                )}
              />
            </Panel>
          </>
        ) : null}
      </div>
    </AppLayout>
  );
}

function ReadinessBanner({ ready }: { ready: boolean }) {
  return (
    <section
      className={`rounded-[12px] border p-4 flex items-center gap-3 ${
        ready
          ? "border-emerald-500/25 bg-emerald-500/[0.06]"
          : "border-red-500/25 bg-red-500/[0.06]"
      }`}
    >
      {ready ? (
        <ShieldCheck size={20} className="text-emerald-300 shrink-0" />
      ) : (
        <XCircle size={20} className="text-red-300 shrink-0" />
      )}
      <div>
        <div
          className={`text-[14px] font-medium ${
            ready ? "text-emerald-200" : "text-red-200"
          }`}
        >
          {ready
            ? "Ready — real voicemail calls can run"
            : "Not ready — real voicemail calls will not run"}
        </div>
        <div className="text-[12px] text-white/50 mt-0.5">
          {ready
            ? "Dialing, AMD, Twilio path and a configured campaign are all in place."
            : "Resolve the blockers below before expecting AMD/voicemail in production."}
        </div>
      </div>
    </section>
  );
}

function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-[12px] border border-white/[0.07] bg-white/[0.02] overflow-hidden">
      <div className="px-4 py-2.5 border-b border-white/[0.05] text-[12px] font-medium text-white/85 uppercase tracking-wider">
        {title}
      </div>
      <div className="divide-y divide-white/[0.04]">{children}</div>
    </section>
  );
}

function KvRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="px-4 py-2.5 flex items-center justify-between gap-3">
      <span className="text-[12px] text-white/55">{label}</span>
      <span
        className={`text-[12px] text-white/85 truncate max-w-[60%] ${
          mono ? "font-mono" : ""
        }`}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}

function BoolRow({
  label,
  value,
  invert,
  neutral,
}: {
  label: string;
  value: boolean;
  /** When true, a `true` value is bad (e.g. dummy credentials). */
  invert?: boolean;
  /** When true, render informationally (grey) rather than good/bad. */
  neutral?: boolean;
}) {
  const good = invert ? !value : value;
  const tone = neutral
    ? "text-white/55"
    : good
      ? "text-emerald-300"
      : "text-red-300";
  return (
    <div className="px-4 py-2.5 flex items-center justify-between gap-3">
      <span className="text-[12px] text-white/55">{label}</span>
      <span className={`text-[12px] inline-flex items-center gap-1 ${tone}`}>
        {neutral ? null : good ? (
          <CheckCircle2 size={12} />
        ) : (
          <XCircle size={12} />
        )}
        {value ? "Yes" : "No"}
      </span>
    </div>
  );
}
