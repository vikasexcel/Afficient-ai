/**
 * CampaignMonitor — real-time execution monitoring dashboard.
 *
 * Polls GET /campaigns/{id}/monitor every 15 seconds using react-query.
 * Read-only — does not modify workflows, executions, or scheduler behaviour.
 */
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import { Button } from "@/components/ui/button";
import { fetchCampaignMonitor } from "@/services/monitor";
import type { MonitorExecution } from "@/types/monitor";

import CampaignOverview from "@/components/campaigns/monitor/CampaignOverview";
import ExecutionMetrics from "@/components/campaigns/monitor/ExecutionMetrics";
import NodeMetrics from "@/components/campaigns/monitor/NodeMetrics";
import LeadExecutionTable from "@/components/campaigns/monitor/LeadExecutionTable";
import ExecutionDetailsDrawer from "@/components/campaigns/monitor/ExecutionDetailsDrawer";
import RetryMonitor from "@/components/campaigns/monitor/RetryMonitor";
import CampaignTimeline from "@/components/campaigns/monitor/CampaignTimeline";

const POLL_MS = 15_000;

export default function CampaignMonitor() {
  const { campaignId } = useParams<{ campaignId: string }>();
  const navigate = useNavigate();
  const [selectedExecution, setSelectedExecution] = useState<MonitorExecution | null>(null);

  const { data, isLoading, isError, dataUpdatedAt, refetch } = useQuery({
    queryKey: ["campaign-monitor", campaignId],
    queryFn: () => fetchCampaignMonitor(campaignId!),
    refetchInterval: POLL_MS,
    enabled: !!campaignId,
    staleTime: 10_000,
    retry: 2,
  });

  if (!campaignId) {
    return (
      <AppLayout>
        <div className="text-white/50 text-sm">Campaign ID missing.</div>
      </AppLayout>
    );
  }

  // Build nodeTypeMap used by multiple sub-components
  const nodeTypeMap: Record<string, string> = {};
  for (const n of data?.workflow_nodes ?? []) {
    nodeTypeMap[n.id] = (n.type ?? "UNKNOWN").toUpperCase();
  }

  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString()
    : null;

  return (
    <AppLayout>
      <div className="max-w-6xl space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3 flex-wrap">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate("/campaigns")}
            className="text-white/50 hover:text-white h-8 px-2 gap-1.5"
          >
            <ArrowLeft size={13} />
            <span className="text-[12px]">Campaigns</span>
          </Button>

          <span className="text-white/20">│</span>

          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-medium text-white">
              {data?.campaign_name ?? "Loading…"}
            </h1>
            <p className="text-[12px] text-white/35 mt-0.5">
              Execution monitor · Polls every 15 seconds
              {lastUpdated && (
                <span className="ml-2 text-white/20">last updated {lastUpdated}</span>
              )}
            </p>
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refetch().then(() => toast.success("Refreshed"))}
            className="text-white/40 hover:text-white h-8 gap-1.5"
          >
            <RefreshCw size={12} />
            <span className="text-[12px]">Refresh</span>
          </Button>
        </div>

        {/* Loading state */}
        {isLoading && !data && (
          <div className="flex items-center justify-center py-20 text-white/40 gap-2">
            <RefreshCw size={16} className="animate-spin" />
            Loading monitor data…
          </div>
        )}

        {/* Error state */}
        {isError && !data && (
          <div className="rounded-xl border border-rose-800/30 bg-rose-900/5 p-6 text-rose-400/80 text-sm text-center">
            Failed to load monitor data. Retrying automatically.
          </div>
        )}

        {/* Dashboard */}
        {data && (
          <>
            <CampaignOverview data={data} />
            <ExecutionMetrics data={data} />
            <NodeMetrics data={data} />
            <LeadExecutionTable
              executions={data.executions}
              nodeTypeMap={nodeTypeMap}
              onSelect={setSelectedExecution}
            />
            <RetryMonitor
              executions={data.executions}
              nodeTypeMap={nodeTypeMap}
              onSelect={setSelectedExecution}
            />
            <CampaignTimeline data={data} />
          </>
        )}
      </div>

      {/* Execution details drawer */}
      <ExecutionDetailsDrawer
        execution={selectedExecution}
        data={data ?? { campaign_id: campaignId, campaign_name: "", campaign_status: "", campaign_created_at: "", lead_list_id: null, metrics: { total_leads: 0, queued_leads: 0, active_calls: 0, completed_calls: 0, failed_calls: 0, failed_executions: 0, pending_leads: 0, progress_percent: 0, retry_count: 0, retry_success_rate: 0, exhausted_retries: 0, average_attempts_per_call: 0 }, executions: [], workflow_nodes: [], workflow_edges: [] }}
        onClose={() => setSelectedExecution(null)}
      />
    </AppLayout>
  );
}
