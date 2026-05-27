import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMe } from "@/store/me";

export default function ProfileCard() {
  const me = useMe((s) => s.data);

  return (
    <div className="space-y-4 max-w-md">
      <div>
        <h2 className="text-[15px] font-medium text-white">Profile</h2>
        <p className="text-[12px] text-white/40 mt-0.5">
          Your account details.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label className="text-[12px] text-white/60">Full name</Label>
        <Input
          value={me?.full_name ?? ""}
          readOnly
          className="bg-white/[0.03] border-white/[0.08] text-white/70"
        />
      </div>

      <div className="space-y-1.5">
        <Label className="text-[12px] text-white/60">Email</Label>
        <Input
          value={me?.email ?? ""}
          readOnly
          className="bg-white/[0.03] border-white/[0.08] text-white/70"
        />
      </div>

      <div className="space-y-1.5">
        <Label className="text-[12px] text-white/60">Role</Label>
        <Input
          value={me?.role ? me.role.charAt(0).toUpperCase() + me.role.slice(1) : ""}
          readOnly
          className="bg-white/[0.03] border-white/[0.08] text-white/70 capitalize"
        />
      </div>
    </div>
  );
}
