import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, Pencil, UserPlus } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { createLead, formatLeadError, listLeadLists, updateLead } from "@/services/leads";
import { leadDisplayName } from "@/types/lead";
import type { Lead, LeadList, LeadStatus } from "@/types/lead";

// ---------------------------------------------------------------------------
// Zod schema
// ---------------------------------------------------------------------------

const PHONE_RE = /^[+\d\s().-]+$/;

const leadSchema = z.object({
  display_name: z
    .string()
    .trim()
    .max(255, "Display name must be 255 characters or fewer")
    .optional()
    .or(z.literal("")),
  first_name: z.string().trim().min(1, "First name is required").max(120),
  last_name: z.string().trim().max(120).optional().or(z.literal("")),
  email: z
    .string()
    .trim()
    .email("Enter a valid email")
    .optional()
    .or(z.literal("")),
  phone: z
    .string()
    .trim()
    .min(1, "Phone is required")
    .regex(PHONE_RE, "Phone contains invalid characters")
    .refine(
      (v) => v.replace(/\D/g, "").length >= 7,
      "Phone needs at least 7 digits"
    )
    .refine(
      (v) => v.replace(/\D/g, "").length <= 15,
      "Phone is too long (max 15 digits)"
    ),
  linkedin_url: z
    .string()
    .trim()
    .url("Enter a valid URL")
    .optional()
    .or(z.literal("")),
  company: z.string().trim().max(255).optional().or(z.literal("")),
  job_title: z.string().trim().max(120).optional().or(z.literal("")),
  status: z.enum([
    "new",
    "contacted",
    "qualified",
    "converted",
    "lost",
  ] as const),
  tags: z.string().trim().optional().or(z.literal("")),
  lead_list_id: z.string().optional(),
});

type FormValues = z.infer<typeof leadSchema>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_OPTIONS: { value: LeadStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "qualified", label: "Qualified" },
  { value: "converted", label: "Converted" },
  { value: "lost", label: "Lost" },
];

const NO_LIST = "__none__";

function toForm(lead: Lead | null): FormValues {
  return {
    display_name: lead?.display_name ?? "",
    first_name: lead?.first_name ?? "",
    last_name: lead?.last_name ?? "",
    email: lead?.email ?? "",
    phone: lead?.phone ?? "",
    linkedin_url: lead?.linkedin_url ?? "",
    company: lead?.company ?? "",
    job_title: lead?.job_title ?? "",
    status: lead?.status ?? "new",
    tags: (lead?.tags ?? []).join(", "),
    lead_list_id: lead?.lead_list_ids?.[0] ?? NO_LIST,
  };
}

function parseTags(raw: string | undefined): string[] | null {
  if (!raw?.trim()) return null;
  const arr = raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  return arr.length ? arr : null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead?: Lead | null;
  onSaved?: (lead: Lead) => void;
};

export default function LeadFormDialog({
  open,
  onOpenChange,
  lead = null,
  onSaved,
}: Props) {
  const isEdit = Boolean(lead);
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(leadSchema),
    defaultValues: toForm(lead),
  });

  // Reset form when dialog opens or target lead changes.
  useEffect(() => {
    if (open) {
      reset(toForm(lead));
      listLeadLists()
        .then(setLeadLists)
        .catch(() => setLeadLists([]));
    }
  }, [open, lead, reset]);

  async function onSubmit(values: FormValues) {
    const tags = parseTags(values.tags);
    try {
      let saved: Lead;
      if (isEdit && lead) {
        saved = await updateLead(lead.id, {
          display_name: values.display_name || null,
          first_name: values.first_name,
          last_name: values.last_name || null,
          email: values.email || null,
          phone: values.phone,
          linkedin_url: values.linkedin_url || null,
          company: values.company || null,
          job_title: values.job_title || null,
          status: values.status,
          tags,
        });
        toast.success(`Updated ${leadDisplayName(saved)}`);
      } else {
        saved = await createLead({
          display_name: values.display_name || null,
          first_name: values.first_name,
          last_name: values.last_name || null,
          email: values.email || null,
          phone: values.phone,
          linkedin_url: values.linkedin_url || null,
          company: values.company || null,
          job_title: values.job_title || null,
          status: values.status,
          tags,
          lead_list_ids:
            values.lead_list_id && values.lead_list_id !== NO_LIST
              ? [values.lead_list_id]
              : null,
        });
        toast.success(`Added ${leadDisplayName(saved)}`);
      }
      onSaved?.(saved);
      onOpenChange(false);
    } catch (err) {
      toast.error(formatLeadError(err, "Could not save lead"));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg p-0 gap-0 bg-[#0c0c10] border border-white/[0.08]"
        showCloseButton
      >
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <div className="flex items-start gap-3">
            <div className="h-9 w-9 shrink-0 rounded-[10px] bg-violet-500/10 border border-violet-500/25 flex items-center justify-center">
              {isEdit ? (
                <Pencil size={15} className="text-violet-300" />
              ) : (
                <UserPlus size={15} className="text-violet-300" />
              )}
            </div>
            <div>
              <DialogTitle className="text-[15px] font-medium text-white">
                {isEdit ? "Edit lead" : "Add lead"}
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/45 mt-0.5">
                {isEdit
                  ? "Update this lead's contact details."
                  : "Add a new prospect to your pipeline."}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form
          onSubmit={handleSubmit(onSubmit)}
          className="px-5 py-4 space-y-3.5 overflow-y-auto max-h-[70vh]"
        >
          {/* Display name */}
          <Field
            label="Lead name"
            hint="How this lead appears in the app"
            error={errors.display_name?.message}
          >
            <Input
              {...register("display_name")}
              placeholder="e.g. Product Lead 1"
              className={inputCls(!!errors.display_name)}
            />
          </Field>

          {/* Name */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field
              label="First name"
              required
              error={errors.first_name?.message}
            >
              <Input
                {...register("first_name")}
                placeholder="Jane"
                autoFocus
                className={inputCls(!!errors.first_name)}
              />
            </Field>
            <Field label="Last name" error={errors.last_name?.message}>
              <Input
                {...register("last_name")}
                placeholder="Doe"
                className={inputCls(!!errors.last_name)}
              />
            </Field>
          </div>

          {/* Contact */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Email" error={errors.email?.message}>
              <Input
                {...register("email")}
                type="email"
                placeholder="jane@acme.com"
                className={inputCls(!!errors.email)}
              />
            </Field>
            <Field label="Phone" required error={errors.phone?.message}>
              <Input
                {...register("phone")}
                placeholder="+1 415 555 1212"
                className={inputCls(!!errors.phone)}
              />
            </Field>
          </div>

          {/* Work */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Company" error={errors.company?.message}>
              <Input
                {...register("company")}
                placeholder="Acme Inc."
                className={inputCls(!!errors.company)}
              />
            </Field>
            <Field label="Job title" error={errors.job_title?.message}>
              <Input
                {...register("job_title")}
                placeholder="Head of Growth"
                className={inputCls(!!errors.job_title)}
              />
            </Field>
          </div>

          {/* LinkedIn */}
          <Field label="LinkedIn URL" error={errors.linkedin_url?.message}>
            <Input
              {...register("linkedin_url")}
              placeholder="https://linkedin.com/in/janedoe"
              className={inputCls(!!errors.linkedin_url)}
            />
          </Field>

          {/* Status + list (or status only in edit mode) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Status" error={errors.status?.message}>
              <Controller
                control={control}
                name="status"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger className={selectCls(!!errors.status)}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[#111114] border-white/[0.08]">
                      {STATUS_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>

            {!isEdit && (
              <Field label="Lead list">
                <Controller
                  control={control}
                  name="lead_list_id"
                  render={({ field }) => (
                    <Select
                      value={field.value ?? NO_LIST}
                      onValueChange={field.onChange}
                    >
                      <SelectTrigger className={selectCls(false)}>
                        <SelectValue placeholder="No list" />
                      </SelectTrigger>
                      <SelectContent
                        className="bg-[#111114] border-white/[0.08]"
                        position="popper"
                      >
                        <SelectItem value={NO_LIST}>No list</SelectItem>
                        {leadLists.map((list) => (
                          <SelectItem key={list.id} value={list.id}>
                            {list.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </Field>
            )}
          </div>

          {/* Tags */}
          <Field label="Tags" hint="Comma-separated" error={errors.tags?.message}>
            <Input
              {...register("tags")}
              placeholder="enterprise, warm, demo-requested"
              className={inputCls(!!errors.tags)}
            />
          </Field>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.05]">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onOpenChange(false)}
              className="text-white/60 hover:text-white"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={isSubmitting}
              className="bg-violet-600 hover:bg-violet-500 text-white min-w-[90px]"
            >
              {isSubmitting ? (
                <Loader2 size={13} className="animate-spin" />
              ) : isEdit ? (
                "Save changes"
              ) : (
                "Add lead"
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function inputCls(hasError: boolean) {
  return cn(
    "h-9 bg-white/[0.03] border-white/[0.09] text-[13px] text-white",
    hasError && "border-red-500/50 focus-visible:ring-red-500/20"
  );
}

function selectCls(hasError: boolean) {
  return cn(
    "w-full h-9 bg-white/[0.03] border-white/[0.09] text-[13px] text-white",
    hasError && "border-red-500/50"
  );
}

function Field({
  label,
  required,
  hint,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <Label className="text-[11px] font-medium text-white/55 uppercase tracking-wide">
          {label}
          {required && <span className="text-red-400 ml-0.5">*</span>}
        </Label>
        {hint && (
          <span className="text-[10.5px] text-white/30">{hint}</span>
        )}
      </div>
      {children}
      {error && (
        <p className="text-[11px] text-red-300 leading-tight">{error}</p>
      )}
    </div>
  );
}
