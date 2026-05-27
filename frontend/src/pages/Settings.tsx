import AppLayout from "@/components/layout/AppLayout";

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

import MembersCard from "@/components/settings/MembersCard";
import OrganizationCard from "@/components/settings/OrganizationCard";
import ProfileCard from "@/components/settings/ProfileCard";
import AppearanceCard from "@/components/settings/AppearanceCard";
import SecurityCard from "@/components/settings/SecurityCard";
import { canManageMembers, useMe } from "@/store/me";

export default function Settings() {
  const me = useMe((s) => s.data);
  const admin = canManageMembers(me?.role);
  return (
    <AppLayout>
      <div className="space-y-8 max-w-5xl">
        <div>
          <h1 className="text-2xl font-medium text-white">Settings</h1>
          <p className="text-[13px] text-white/40 mt-1">
            Manage your organization and account
          </p>
        </div>

        <Tabs defaultValue={admin ? "members" : "profile"}>
          <TabsList className="bg-transparent border-b border-white/[0.05] rounded-none w-full justify-start h-auto p-0 gap-1">
            {admin && (
              <>
                <TabsTrigger
                  value="members"
                  className="data-[state=active]:bg-transparent data-[state=active]:text-white data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-violet-500 rounded-none text-white/50 text-[13px] px-3 pb-2.5 pt-0 -mb-px"
                >
                  Members
                </TabsTrigger>
                <TabsTrigger
                  value="organization"
                  className="data-[state=active]:bg-transparent data-[state=active]:text-white data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-violet-500 rounded-none text-white/50 text-[13px] px-3 pb-2.5 pt-0 -mb-px"
                >
                  Organization
                </TabsTrigger>
              </>
            )}
            <TabsTrigger
              value="profile"
              className="data-[state=active]:bg-transparent data-[state=active]:text-white data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-violet-500 rounded-none text-white/50 text-[13px] px-3 pb-2.5 pt-0 -mb-px"
            >
              Profile
            </TabsTrigger>
            <TabsTrigger
              value="appearance"
              className="data-[state=active]:bg-transparent data-[state=active]:text-white data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-violet-500 rounded-none text-white/50 text-[13px] px-3 pb-2.5 pt-0 -mb-px"
            >
              Appearance
            </TabsTrigger>
            <TabsTrigger
              value="security"
              className="data-[state=active]:bg-transparent data-[state=active]:text-white data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-violet-500 rounded-none text-white/50 text-[13px] px-3 pb-2.5 pt-0 -mb-px"
            >
              Security
            </TabsTrigger>
          </TabsList>

          {admin && (
            <TabsContent value="members" className="mt-6">
              <MembersCard />
            </TabsContent>
          )}

          {admin && (
            <TabsContent value="organization" className="mt-6">
              <OrganizationCard />
            </TabsContent>
          )}

          <TabsContent value="profile" className="mt-6">
            <ProfileCard />
          </TabsContent>

          <TabsContent value="appearance" className="mt-6">
            <AppearanceCard />
          </TabsContent>

          <TabsContent value="security" className="mt-6">
            <SecurityCard />
          </TabsContent>
        </Tabs>
      </div>
    </AppLayout>
  );
}