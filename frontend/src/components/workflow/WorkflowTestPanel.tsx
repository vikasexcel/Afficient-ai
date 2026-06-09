/**
 * WorkflowTestPanel
 *
 * Slide-in panel that lets users test a workflow end-to-end by specifying
 * a test email address and phone number.  Execution logs are streamed back
 * and displayed step-by-step.
 */
import { useState } from "react";
import {
  X,
  Play,
  Mail,
  Phone,
  CheckCircle2,
  XCircle,
  SkipForward,
  Loader2,
  GitBranch,
  PhoneCall,
  StopCircle,
  Clock,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { WorkflowTestLogEntry, WorkflowTestResponse } from "@/types/workflow";
import { testWorkflow } from "@/services/workflow";

interface Props {
  campaignId: string;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function statusIcon(status: WorkflowTestLogEntry["status"]) {
  switch (status) {
    case "completed":
      return <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />;
    case "condition_true":
      return <GitBranch size={14} className="text-emerald-400 shrink-0" />;
    case "condition_false":
      return <GitBranch size={14} className="text-amber-400 shrink-0" />;
    case "skipped":
      return <SkipForward size={14} className="text-white/40 shrink-0" />;
    case "failed":
      return <XCircle size={14} className="text-red-400 shrink-0" />;
    case "running":
      return <Loader2 size={14} className="text-indigo-400 animate-spin shrink-0" />;
    default:
      return <AlertCircle size={14} className="text-white/40 shrink-0" />;
  }
}

function nodeTypeIcon(type: string) {
  switch (type.toUpperCase()) {
    case "EMAIL":
      return <Mail size={12} className="text-white/50" />;
    case "CALL":
      return <PhoneCall size={12} className="text-white/50" />;
    case "WAIT":
      return <Clock size={12} className="text-white/50" />;
    case "CONDITION":
      return <GitBranch size={12} className="text-white/50" />;
    case "STOP":
      return <StopCircle size={12} className="text-white/50" />;
    default:
      return null;
  }
}

function statusBadge(result: WorkflowTestResponse["result"]) {
  const base = "text-[11px] font-medium px-2 py-0.5 rounded-full";
  if (result === "completed")
    return <span className={`${base} bg-emerald-500/15 text-emerald-400`}>Completed</span>;
  if (result === "stopped")
    return <span className={`${base} bg-amber-500/15 text-amber-400`}>Stopped</span>;
  return <span className={`${base} bg-red-500/15 text-red-400`}>Failed</span>;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function WorkflowTestPanel({ campaignId, onClose }: Props) {
  const [testEmail, setTestEmail] = useState("kumaranurad604@gmail.com");
  const [testPhone, setTestPhone] = useState("+917541006707");
  const [skipWait, setSkipWait] = useState(true);
  const [running, setRunning] = useState(false);
  const [response, setResponse] = useState<WorkflowTestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    if (running) return;
    setRunning(true);
    setResponse(null);
    setError(null);
    try {
      const result = await testWorkflow(campaignId, {
        test_email: testEmail,
        test_phone: testPhone || undefined,
        skip_wait: skipWait,
      });
      setResponse(result);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err instanceof Error ? err.message : "Test run failed");
      setError(msg);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#0d0d14] border-l border-white/[0.07] w-[420px] shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.07]">
        <div className="flex items-center gap-2">
          <Play size={14} className="text-indigo-400" />
          <span className="text-white text-sm font-medium">Test Workflow</span>
        </div>
        <button
          onClick={onClose}
          className="text-white/40 hover:text-white/70 transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex flex-col gap-4 p-4 overflow-y-auto flex-1">
        {/* Config form */}
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-white/60 text-[11px] uppercase tracking-widest flex items-center gap-1.5">
              <Mail size={11} />
              Test email address
            </Label>
            <Input
              type="email"
              value={testEmail}
              onChange={(e) => setTestEmail(e.target.value)}
              placeholder="recipient@example.com"
              className="bg-white/5 border-white/10 text-white text-sm placeholder:text-white/20"
              disabled={running}
            />
            <p className="text-white/30 text-[10px]">
              The workflow will send the email to this address and check for replies.
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label className="text-white/60 text-[11px] uppercase tracking-widest flex items-center gap-1.5">
              <Phone size={11} />
              Test phone number
            </Label>
            <Input
              type="tel"
              value={testPhone}
              onChange={(e) => setTestPhone(e.target.value)}
              placeholder="+917541006707"
              className="bg-white/5 border-white/10 text-white text-sm placeholder:text-white/20"
              disabled={running}
            />
            <p className="text-white/30 text-[10px]">
              Used as the call destination. Overrides the CALL node's phone when set.
            </p>
          </div>

          <div className="flex items-center justify-between py-1">
            <div className="flex flex-col gap-0.5">
              <span className="text-white/60 text-[11px] uppercase tracking-widest">Skip wait nodes</span>
              <span className="text-white/30 text-[10px]">Run instantly without waiting</span>
            </div>
            <Switch
              checked={skipWait}
              onCheckedChange={setSkipWait}
              disabled={running}
            />
          </div>
        </div>

        {/* Run button */}
        <Button
          onClick={handleRun}
          disabled={running || !testEmail}
          className="w-full bg-indigo-600 hover:bg-indigo-500 text-white gap-2"
        >
          {running ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Running test…
            </>
          ) : (
            <>
              <Play size={14} />
              Run Test
            </>
          )}
        </Button>

        {/* Error */}
        {error && !running && (
          <div className="flex items-start gap-2 p-3 rounded-md bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
            <XCircle size={14} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Results */}
        {response && (
          <div className="flex flex-col gap-3">
            {/* Summary */}
            <div className="flex items-center justify-between py-2 px-3 rounded-md bg-white/[0.03] border border-white/[0.06]">
              <span className="text-white/50 text-xs">Result</span>
              {statusBadge(response.result)}
            </div>

            {response.error && (
              <div className="flex items-start gap-2 p-3 rounded-md bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                <XCircle size={14} className="shrink-0 mt-0.5" />
                <span>{response.error}</span>
              </div>
            )}

            {/* Step-by-step logs */}
            <div className="flex flex-col gap-0.5">
              <p className="text-white/40 text-[11px] uppercase tracking-widest mb-1">
                Execution logs
              </p>

              {response.logs.map((entry) => (
                <div
                  key={entry.step}
                  className="flex flex-col gap-1 py-2 px-3 rounded-md bg-white/[0.02] border border-white/[0.04] hover:bg-white/[0.04] transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-white/25 text-[10px] w-4 text-right shrink-0">
                      {entry.step}
                    </span>
                    {statusIcon(entry.status)}
                    <div className="flex items-center gap-1 min-w-0">
                      {nodeTypeIcon(entry.node_type)}
                      <span className="text-white/80 text-xs font-medium truncate">
                        {entry.node_label}
                      </span>
                    </div>
                    <span className="ml-auto text-white/25 text-[10px] shrink-0">
                      {formatTime(entry.timestamp)}
                    </span>
                  </div>

                  <p className="text-white/50 text-[11px] pl-8 leading-relaxed">
                    {entry.message}
                  </p>

                  {/* Expandable output (only for non-trivial outputs) */}
                  {entry.output && Object.keys(entry.output).length > 0 && (
                    <details className="pl-8">
                      <summary className="text-white/25 text-[10px] cursor-pointer hover:text-white/50 list-none flex items-center gap-1">
                        <span>▶ details</span>
                      </summary>
                      <pre className="mt-1 text-[10px] text-white/30 overflow-x-auto whitespace-pre-wrap break-all leading-relaxed">
                        {JSON.stringify(entry.output, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
