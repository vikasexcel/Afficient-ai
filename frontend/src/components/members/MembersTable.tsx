import { MoreHorizontal, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import type { Member, Role } from "@/services/members";

type Props = {
  members: Member[];
  loading: boolean;
  canManage: boolean;
  currentMembershipId?: string | null;
  onChangeRole: (m: Member, role: Role) => void;
  onResetPassword: (m: Member) => void;
  onRemove: (m: Member) => void;
};

const ROLE_OPTIONS: Role[] = ["owner", "admin", "agent", "member"];

function roleLabel(role: Role) {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export function MembersTable({
  members,
  loading,
  canManage,
  currentMembershipId,
  onChangeRole,
  onResetPassword,
  onRemove,
}: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="border-white/[0.05] hover:bg-transparent">
          <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
            Name
          </TableHead>
          <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
            Email
          </TableHead>
          <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
            Role
          </TableHead>
          <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
            Status
          </TableHead>
          <TableHead className="w-12" />
        </TableRow>
      </TableHeader>

      <TableBody>
        {loading && (
          <TableRow>
            <TableCell colSpan={5} className="py-8">
              <div className="flex items-center justify-center gap-2 text-white/40 text-[13px]">
                <Loader2 size={14} className="animate-spin" />
                Loading members…
              </div>
            </TableCell>
          </TableRow>
        )}

        {!loading && members.length === 0 && (
          <TableRow>
            <TableCell colSpan={5} className="py-8">
              <div className="text-center text-white/40 text-[13px]">
                No members yet.
              </div>
            </TableCell>
          </TableRow>
        )}

        {!loading &&
          members.map((m) => {
            const isSelf = m.membership_id === currentMembershipId;
            const isOwner = m.role === "owner";
            const canTouchRow = canManage && !isOwner;

            return (
              <TableRow
                key={m.membership_id}
                className="border-white/[0.05] hover:bg-white/[0.02]"
              >
                <TableCell className="text-[13px] font-medium text-white/90">
                  {m.full_name}
                  {isSelf && (
                    <span className="ml-2 text-[11px] text-white/30">
                      (you)
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-[13px] text-white/55">
                  {m.email}
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className="border-white/[0.08] bg-white/[0.03] text-white/70 font-normal text-[11px] capitalize"
                  >
                    {roleLabel(m.role)}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={
                      m.status === "active"
                        ? "border-emerald-500/20 bg-emerald-500/[0.08] text-emerald-300 font-normal text-[11px] capitalize"
                        : "border-amber-500/20 bg-amber-500/[0.08] text-amber-300 font-normal text-[11px] capitalize"
                    }
                  >
                    {m.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  {canManage && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-white/40 hover:text-white"
                          disabled={!canTouchRow && isOwner}
                          aria-label="Actions"
                        >
                          <MoreHorizontal size={14} />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="end"
                        className="w-44 bg-[#111114] border-white/[0.08]"
                      >
                        <DropdownMenuLabel className="text-[11px] text-white/40 font-normal">
                          Manage member
                        </DropdownMenuLabel>
                        <DropdownMenuSeparator className="bg-white/[0.06]" />

                        <DropdownMenuSub>
                          <DropdownMenuSubTrigger
                            disabled={!canTouchRow}
                            className="text-[12px]"
                          >
                            Edit role
                          </DropdownMenuSubTrigger>
                          <DropdownMenuSubContent className="bg-[#111114] border-white/[0.08]">
                            <DropdownMenuRadioGroup
                              value={m.role}
                              onValueChange={(v) =>
                                onChangeRole(m, v as Role)
                              }
                            >
                              {ROLE_OPTIONS.map((r) => (
                                <DropdownMenuRadioItem
                                  key={r}
                                  value={r}
                                  className="text-[12px] capitalize"
                                >
                                  {roleLabel(r)}
                                </DropdownMenuRadioItem>
                              ))}
                            </DropdownMenuRadioGroup>
                          </DropdownMenuSubContent>
                        </DropdownMenuSub>

                        <DropdownMenuItem
                          className="text-[12px]"
                          onClick={() => onResetPassword(m)}
                        >
                          Reset password
                        </DropdownMenuItem>

                        <DropdownMenuSeparator className="bg-white/[0.06]" />
                        <DropdownMenuItem
                          disabled={!canTouchRow || isSelf}
                          className="text-[12px] text-red-400 focus:text-red-400 focus:bg-red-500/[0.08]"
                          onClick={() => onRemove(m)}
                        >
                          Remove from org
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
      </TableBody>
    </Table>
  );
}
