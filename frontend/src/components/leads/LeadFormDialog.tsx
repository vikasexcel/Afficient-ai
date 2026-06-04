import { useEffect, useMemo, useState } from "react";
import { Loader2, UserPlus, Pencil } from "lucide-react";
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
import { formatApiError } from "@/lib/apiError";
import { createLead, listLeadLists, updateLead } from "@/services/lead";
import type { Lead, LeadList, LeadStatus } from "@/types/lead";

const STATUS_OPTIONS: { value: LeadStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "qualified", label: "Qualified" },
  { value: "converted", label: "Converted" },
  { value: "lost", label: "Lost" },
];

const NO_LIST = "__none__";

// Allow common phone formatting; require 7–15 digits (mirrors backend).
const PHONE_ALLOWED = /^[+\d\s().\-]+$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

type FormValues = {
  name: string;
  email: string;
  phone: string;
  company: string;
  industry: string;
  tagsRaw: string;
  leadListId: string;
  status: LeadStatus;
};

function leadToForm(lead: Lead | null): FormValues {
  return {
    name: lead?.name ?? "",
    email: lead?.email ?? "",
    phone: lead?.phone ?? "",
    company: lead?.company ?? "",
    industry: lead?.industry ?? "",
    tagsRaw: (lead?.tags ?? []).join(", "),
    leadListId: lead?.lead_list_id ?? NO_LIST,
    status: lead?.status ?? "new",
  };
}

function parseTags(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Provide a lead to edit; omit (or null) to add a new lead. */
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
  const [values, setValues] = useState<FormValues>(() => leadToForm(lead));
  const [errors, setErrors] = useState<Partial<Record<keyof FormValues, string>>>(
    {}
  );
  const [submitting, setSubmitting] = useState(false);
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);

  // Reset the form whenever the dialog opens (or the target lead changes).
  useEffect(() => {
    if (open) {
      setValues(leadToForm(lead));
      setErrors({});
      void listLeadLists()
        .then(setLeadLists)
        .catch(() => setLeadLists([]));
    }
  }, [open, lead]);

  function set<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  }

  const validate = useMemo(
    () => () => {
      const next: Partial<Record<keyof FormValues, string>> = {};
      if (!values.name.trim()) next.name = "Name is required";

      const phone = values.phone.trim();
      if (!phone) {
        next.phone = "Phone is required";
      } else if (!PHONE_ALLOWED.test(phone)) {
        next.phone = "Phone contains invalid characters";
      } else {
        const digits = phone.replace(/\D/g, "");
        if (digits.length < 7) next.phone = "Phone needs at least 7 digits";
        else if (digits.length > 15) next.phone = "Phone is too long (max 15 digits)";
      }

      if (values.email.trim() && !EMAIL_RE.test(values.email.trim())) {
        next.email = "Enter a valid email address";
      }
      return next;
    },
    [values]
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const next = validate();
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setSubmitting(true);
    try {
      const tags = parseTags(values.tagsRaw);
      let saved: Lead;
      if (isEdit && lead) {
        saved = await updateLead(lead.id, {
          name: values.name.trim(),
          email: values.email.trim() || null,
          phone: values.phone.trim(),
          company: values.company.trim() || null,
          industry: values.industry.trim() || null,
          status: values.status,
          tags,
        });
        toast.success(`Updated ${saved.name}`);
      } else {
        saved = await createLead({
          name: values.name.trim(),
          email: values.email.trim() || null,
          phone: values.phone.trim(),
          company: values.company.trim() || null,
          industry: values.industry.trim() || null,
          status: values.status,
          tags,
          lead_list_id:
            values.leadListId === NO_LIST ? null : values.leadListId,
        });
        toast.success(`Added ${saved.name}`);
      }
      onSaved?.(saved);
      onOpenChange(false);
    } catch (err) {
      toast.error(formatApiError(err, "Could not save lead"));
    } finally {
      setSubmitting(false);
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
              <DialogTitle className="text-[15px] text-white">
                {isEdit ? "Edit lead" : "Add lead"}
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/45 mt-0.5">
                {isEdit
                  ? "Update this lead's details."
                  : "Manually add a new prospect to your pipeline."}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="px-5 py-4 space-y-3.5">
          <Field label="Name" required error={errors.name}>
            <Input
              value={values.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="Jane Doe"
              className="h-9 bg-white/[0.03] border-white/[0.09] text-[13px]"
              autoFocus
            />
          </Field>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Email" error={errors.email}>
              <Input
                value={values.email}
                onChange={(e) => set("email", e.target.value)}
                placeholder="jane@acme.com"
                className="h-9 bg-white/[0.03] border-white/[0.09] text-[13px]"
              />
            </Field>
            <Field label="Phone" required error={errors.phone}>
              <Input
                value={values.phone}
                onChange={(e) => set("phone", e.target.value)}
                placeholder="+1 415 555 1212"
                className="h-9 bg-white/[0.03] border-white/[0.09] text-[13px]"
              />
            </Field>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Company">
              <Input
                value={values.company}
                onChange={(e) => set("company", e.target.value)}
                placeholder="Acme Inc."
                className="h-9 bg-white/[0.03] border-white/[0.09] text-[13px]"
              />
            </Field>
            <Field label="Industry">
              <Input
                value={values.industry}
                onChange={(e) => set("industry", e.target.value)}
                placeholder="Software"
                className="h-9 bg-white/[0.03] border-white/[0.09] text-[13px]"
              />
            </Field>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {isEdit ? (
              <Field label="Status">
                <Select
                  value={values.status}
                  onValueChange={(v) => set("status", v as LeadStatus)}
                >
                  <SelectTrigger className="w-full h-9 bg-white/[0.03] border-white/[0.09] text-[13px]">
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
              </Field>
            ) : (
              <Field label="Lead list">
                <Select
                  value={values.leadListId}
                  onValueChange={(v) => set("leadListId", v)}
                >
                  <SelectTrigger className="w-full h-9 bg-white/[0.03] border-white/[0.09] text-[13px]">
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
              </Field>
            )}
            <Field label="Tags" hint="Comma-separated">
              <Input
                value={values.tagsRaw}
                onChange={(e) => set("tagsRaw", e.target.value)}
                placeholder="warm, demo-requested"
                className="h-9 bg-white/[0.03] border-white/[0.09] text-[13px]"
              />
            </Field>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
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
              disabled={submitting}
              className="bg-violet-600 hover:bg-violet-500 text-white"
            >
              {submitting && <Loader2 size={13} className="animate-spin" />}
              {isEdit ? "Save changes" : "Add lead"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
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
    <div>
      <div className="flex items-center justify-between mb-1">
        <Label className="text-[11px] font-medium text-white/55">
          {label}
          {required && <span className="text-red-400 ml-0.5">*</span>}
        </Label>
        {hint && <span className="text-[10.5px] text-white/35">{hint}</span>}
      </div>
      {children}
      {error && (
        <p className={cn("text-[11px] text-red-300 mt-1")}>{error}</p>
      )}
    </div>
  );
}
