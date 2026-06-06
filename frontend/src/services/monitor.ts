import { api } from "./auth";
import type { CampaignMonitorPayload } from "@/types/monitor";

export async function fetchCampaignMonitor(
  campaignId: string
): Promise<CampaignMonitorPayload> {
  const { data } = await api.get<CampaignMonitorPayload>(
    `/campaigns/${campaignId}/monitor`
  );
  return data;
}
