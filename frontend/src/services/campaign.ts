import { api } from "./auth";

export async function createCampaign(data: { name: string }) {
  const res = await api.post("/campaigns", data);
  return res.data;
}