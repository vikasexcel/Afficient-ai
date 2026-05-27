import { api } from "./auth";

export type Organization = { id: string; name: string };

export async function getOrganization(): Promise<Organization> {
  const res = await api.get<Organization>("/organization");
  return res.data;
}

export async function renameOrganization(name: string): Promise<Organization> {
  const res = await api.patch<Organization>("/organization", { name });
  return res.data;
}

export async function transferOwnership(membership_id: string): Promise<void> {
  await api.post("/organization/transfer-ownership", { membership_id });
}

export async function deleteOrganization(): Promise<void> {
  await api.delete("/organization");
}
