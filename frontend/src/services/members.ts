import { api } from "./auth";

export type Role = "owner" | "admin" | "agent" | "member";
export type MemberStatus = "active" | "pending";

export type Member = {
  membership_id: string;
  user_id: string;
  full_name: string;
  email: string;
  role: Role;
  status: MemberStatus;
};

export type CreateMemberInput = {
  full_name: string;
  email: string;
  password?: string;
  role: Role;
};

export type CreateMemberResult = {
  member: Member;
  temp_password: string | null;
  account_exists: boolean;
  email_sent: boolean;
};

export async function listMembers(): Promise<Member[]> {
  const res = await api.get<Member[]>("/members");
  return res.data;
}

export async function createMember(
  data: CreateMemberInput
): Promise<CreateMemberResult> {
  const res = await api.post<CreateMemberResult>("/members", data);
  return res.data;
}

export async function updateRole(
  membership_id: string,
  role: Role
): Promise<Member> {
  const res = await api.patch<Member>(`/members/${membership_id}/role`, {
    role,
  });
  return res.data;
}

export async function resetMemberPassword(
  membership_id: string
): Promise<{ temp_password: string; email_sent: boolean }> {
  const res = await api.post<{ temp_password: string; email_sent: boolean }>(
    `/members/${membership_id}/reset-password`
  );
  return res.data;
}

export type RemoveMemberResult = {
  removed: boolean;
  user_deleted: boolean;
  email_sent: boolean;
};

export async function removeMember(
  membership_id: string
): Promise<RemoveMemberResult> {
  const res = await api.delete<RemoveMemberResult>(`/members/${membership_id}`);
  return res.data;
}
