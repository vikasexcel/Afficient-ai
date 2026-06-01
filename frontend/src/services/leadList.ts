/**
 * Compatibility shim for the original lead-list service.
 *
 * The canonical client lives in ``services/lead.ts`` now. This file is
 * kept so existing imports (notably the campaign dialog) keep working
 * without churn.
 */

import { listLeadLists as listLeadListsImpl } from "./lead";

export type { LeadList } from "@/types/lead";
import type { LeadList } from "@/types/lead";

export async function listLeadLists(): Promise<LeadList[]> {
  return listLeadListsImpl();
}

export function findLeadList(
  lists: LeadList[],
  id: string | null | undefined
): LeadList | undefined {
  if (!id) return undefined;
  return lists.find((l) => l.id === id);
}
