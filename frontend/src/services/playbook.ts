import { api } from "./auth";

export type PlaybookStatus = "draft" | "active" | "archived";
export type PlaybookFramework = "BANT" | "MEDDICC" | "CUSTOM";

export type PlaybookField = {
  id?: string;
  key: string;
  display_name: string;
  description?: string | null;
  weight: number;
  required: boolean;
  cue_patterns: string[];
  position: number;
  created_at?: string;
  updated_at?: string;
};

export type PlaybookSummary = {
  id: string;
  name: string;
  description: string | null;
  status: PlaybookStatus;
  framework: PlaybookFramework;
  persona_name: string;
  version: number;
  field_count: number;
  created_at: string;
  updated_at: string;
};

export type PlaybookBranch = {
  id: string;
  name: string;
  priority?: number;
  once?: boolean;
  when?: Record<string, unknown>;
  then?: Record<string, unknown>;
};

export type PlaybookDetail = {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  status: PlaybookStatus;
  framework: PlaybookFramework;
  persona_name: string;
  system_prompt: string | null;
  opening_line: string | null;
  default_objective: string | null;
  voice_id: string | null;
  default_context: Record<string, unknown> | null;
  disqualifying_patterns: string[] | null;
  branches?: PlaybookBranch[] | null;
  version: number;
  fields: PlaybookField[];
  created_at: string;
  updated_at: string;
};

export type CreatePlaybookInput = {
  name: string;
  description?: string;
  framework?: PlaybookFramework;
  persona_name?: string;
  system_prompt?: string;
  opening_line?: string;
  default_objective?: string;
  voice_id?: string;
  default_context?: Record<string, unknown>;
  disqualifying_patterns?: string[];
  fields?: Omit<PlaybookField, "id" | "created_at" | "updated_at">[];
  branches?: PlaybookBranch[];
};

export type UpdatePlaybookInput = Partial<CreatePlaybookInput>;

export type PlaybookTestInput = {
  user_text: string;
  extra_context?: Record<string, unknown>;
};

export type PlaybookTestResult = {
  rendered_system_prompt: string;
  qualification_before: Record<string, unknown>;
  qualification_after: Record<string, unknown>;
  newly_set_fields: string[];
  branches_fired: string[];
};

export type PlaybookVersion = {
  id: string;
  playbook_id: string;
  version: number;
  payload: Record<string, unknown>;
  created_at: string;
  created_by: string | null;
};

export async function listPlaybooks(activeOnly = false): Promise<PlaybookSummary[]> {
  const res = await api.get<{ playbooks: PlaybookSummary[] }>("/playbooks", {
    params: activeOnly ? { active_only: true } : undefined,
  });
  return res.data.playbooks;
}

export async function getPlaybook(id: string): Promise<PlaybookDetail> {
  const res = await api.get<PlaybookDetail>(`/playbooks/${id}`);
  return res.data;
}

export async function createPlaybook(data: CreatePlaybookInput): Promise<PlaybookDetail> {
  const res = await api.post<PlaybookDetail>("/playbooks", data);
  return res.data;
}

export async function updatePlaybook(
  id: string,
  data: UpdatePlaybookInput
): Promise<PlaybookDetail> {
  const res = await api.patch<PlaybookDetail>(`/playbooks/${id}`, data);
  return res.data;
}

export async function publishPlaybook(id: string): Promise<PlaybookDetail> {
  const res = await api.post<PlaybookDetail>(`/playbooks/${id}/publish`);
  return res.data;
}

export async function archivePlaybook(id: string): Promise<PlaybookDetail> {
  const res = await api.post<PlaybookDetail>(`/playbooks/${id}/archive`);
  return res.data;
}

export async function duplicatePlaybook(id: string): Promise<PlaybookDetail> {
  const res = await api.post<PlaybookDetail>(`/playbooks/${id}/duplicate`);
  return res.data;
}

export async function testPlaybook(
  id: string,
  data: PlaybookTestInput
): Promise<PlaybookTestResult> {
  const res = await api.post<PlaybookTestResult>(`/playbooks/${id}/test`, data);
  return res.data;
}

export async function listPlaybookVersions(id: string): Promise<PlaybookVersion[]> {
  const res = await api.get<{ versions: PlaybookVersion[] }>(
    `/playbooks/${id}/versions`
  );
  return res.data.versions;
}

export async function previewPlaybookPrompt(id: string): Promise<{
  rendered_system_prompt: string;
  placeholders: string[];
}> {
  const res = await api.get<{ rendered_system_prompt: string; placeholders: string[] }>(
    `/playbooks/${id}/preview`
  );
  return res.data;
}
