import AppLayout from "@/components/layout/AppLayout";
import CreateCampaignDialog from "@/components/campaign/CreateCampaignDialog";
import { useMe, canUseCampaigns } from "@/store/me";

export default function Campaigns() {
  const me = useMe((s) => s.data);
  const canCreate = canUseCampaigns(me?.role);

  return (
    <AppLayout>
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-medium text-white">Campaigns</h1>
          <p className="text-[13px] text-white/40 mt-1">
            {canCreate
              ? "Manage AI outbound workflows"
              : "View-only access — contact an admin to create campaigns"}
          </p>
        </div>

        {canCreate && <CreateCampaignDialog />}
      </div>
    </AppLayout>
  );
}