/** Predefined objection types (mirrors backend ``PREDEFINED_OBJECTIONS``). */

export type ObjectionType =
  | "not_interested"
  | "busy"
  | "send_information"
  | "already_using_another_solution"
  | "call_me_later"
  | "no_budget"
  | "no_need"
  | "custom";

export const OBJECTION_TYPE_OPTIONS: {
  value: ObjectionType;
  label: string;
  defaultTrigger: string;
}[] = [
  {
    value: "not_interested",
    label: "Not Interested",
    defaultTrigger: "Not interested",
  },
  { value: "busy", label: "Busy", defaultTrigger: "I'm busy right now" },
  {
    value: "send_information",
    label: "Send Information",
    defaultTrigger: "Can you send me some information?",
  },
  {
    value: "already_using_another_solution",
    label: "Already Using Another Solution",
    defaultTrigger: "We already have something",
  },
  {
    value: "call_me_later",
    label: "Call Me Later",
    defaultTrigger: "Call me later",
  },
  { value: "no_budget", label: "No Budget", defaultTrigger: "We have no budget" },
  { value: "no_need", label: "No Need", defaultTrigger: "We don't need this" },
  { value: "custom", label: "Custom", defaultTrigger: "" },
];

export function objectionTypeLabel(value: string): string {
  return (
    OBJECTION_TYPE_OPTIONS.find((o) => o.value === value)?.label ??
    value.replace(/_/g, " ")
  );
}
