import { api } from "./auth";
import type {
  WorkflowGraph,
  WorkflowGraphResponse,
  WorkflowValidationResponse,
  WorkflowTemplate,
  WorkflowTemplateListResponse,
  WorkflowVersionListResponse,
  WorkflowVersionDetail,
  WorkflowRestoreResponse,
} from "@/types/workflow";

export async function getWorkflow(
  campaignId: string
): Promise<WorkflowGraphResponse> {
  const { data } = await api.get<WorkflowGraphResponse>(
    `/campaigns/${campaignId}/workflow`
  );
  return data;
}

export async function saveWorkflow(
  campaignId: string,
  graph: WorkflowGraph
): Promise<WorkflowGraphResponse> {
  const { data } = await api.put<WorkflowGraphResponse>(
    `/campaigns/${campaignId}/workflow`,
    graph
  );
  return data;
}

export async function validateWorkflow(
  campaignId: string,
  graph: WorkflowGraph
): Promise<WorkflowValidationResponse> {
  const { data } = await api.post<WorkflowValidationResponse>(
    `/campaigns/${campaignId}/workflow/validate`,
    graph
  );
  return data;
}

// ---------------------------------------------------------------------------
// Workflow templates
// ---------------------------------------------------------------------------

export async function listTemplates(category?: string): Promise<WorkflowTemplateListResponse> {
  const { data } = await api.get<WorkflowTemplateListResponse>("/workflow-templates", {
    params: category ? { category } : undefined,
  });
  return data;
}

export async function getTemplate(templateId: string): Promise<WorkflowTemplate> {
  const { data } = await api.get<WorkflowTemplate>(`/workflow-templates/${templateId}`);
  return data;
}

export async function cloneTemplate(templateId: string): Promise<WorkflowTemplate> {
  const { data } = await api.post<WorkflowTemplate>(
    `/workflow-templates/${templateId}/clone`,
    {}
  );
  return data;
}

// ---------------------------------------------------------------------------
// Workflow version history (Phase 3C)
// ---------------------------------------------------------------------------

export async function listWorkflowVersions(
  campaignId: string
): Promise<WorkflowVersionListResponse> {
  const { data } = await api.get<WorkflowVersionListResponse>(
    `/campaigns/${campaignId}/workflow/versions`
  );
  return data;
}

export async function getWorkflowVersion(
  campaignId: string,
  version: number
): Promise<WorkflowVersionDetail> {
  const { data } = await api.get<WorkflowVersionDetail>(
    `/campaigns/${campaignId}/workflow/versions/${version}`
  );
  return data;
}

export async function restoreWorkflowVersion(
  campaignId: string,
  version: number
): Promise<WorkflowRestoreResponse> {
  const { data } = await api.post<WorkflowRestoreResponse>(
    `/campaigns/${campaignId}/workflow/versions/${version}/restore`
  );
  return data;
}
