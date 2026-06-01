import { useCallback, useMemo, useRef, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import {
  BookOpen,
  CalendarClock,
  Clock,
  Loader2,
  Plus,
  Rocket,
  Save,
  Target,
  Users,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

import {
  activateCampaign,
  createCampaign,
  newDraftId,
  upsertDraft,
} from "@/services/campaign";
import {
  listPlaybooks,
  type PlaybookSummary,
} from "@/services/playbook";
import { listLeadLists, type LeadList } from "@/services/leadList";
import {
  WEEKDAYS,
  type CampaignDraft,
  type Weekday,
} from "@/types/campaign";

/* -------------------------------------------------------------------------- */
/* Validation                                                                 */
/* -------------------------------------------------------------------------- */

const TIME_RE = /^\d{2}:\d{2}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

const businessHoursSchema = z
  .object({
    days: z
      .array(
        z.enum(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
      )
      .min(1, "Pick at least one calling day"),
    start: z.string().regex(TIME_RE, "Start time required"),
    end: z.string().regex(TIME_RE, "End time required"),
    skip_holidays: z.boolean(),
  })
  .refine((bh) => bh.start < bh.end, {
    path: ["end"],
    message: "End time must be after start time",
  });

const scheduleSchema = z
  .object({
    start_immediately: z.boolean(),
    date: z.string().nullable(),
    time: z.string().nullable(),
    timezone: z.string().min(1, "Timezone required"),
  })
  .superRefine((s, ctx) => {
    if (s.start_immediately) return;
    if (!s.date || !DATE_RE.test(s.date)) {
      ctx.addIssue({
        code: "custom",
        path: ["date"],
        message: "Start date required",
      });
    }
    if (!s.time || !TIME_RE.test(s.time)) {
      ctx.addIssue({
        code: "custom",
        path: ["time"],
        message: "Start time required",
      });
    }
  });

const launchSchema = z.object({
  name: z
    .string()
    .trim()
    .min(2, "Name must be at least 2 characters")
    .max(120, "Name is too long"),
  playbook_id: z.string().min(1, "Pick a playbook"),
  lead_list_id: z.string().min(1, "Pick a lead list"),
  schedule: scheduleSchema,
  business_hours: businessHoursSchema,
});

type FormValues = z.infer<typeof launchSchema>;

/* -------------------------------------------------------------------------- */
/* Constants                                                                  */
/* -------------------------------------------------------------------------- */

const CURATED_TIMEZONES = [
  "UTC",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Berlin",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

function resolveLocalTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function todayLocalISODate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function defaultDraft(): CampaignDraft {
  return {
    name: "",
    playbook_id: null,
    lead_list_id: null,
    schedule: {
      date: todayLocalISODate(),
      time: "09:00",
      timezone: resolveLocalTimezone(),
      start_immediately: false,
    },
    business_hours: {
      days: ["mon", "tue", "wed", "thu", "fri"],
      start: "09:00",
      end: "18:00",
      skip_holidays: true,
    },
  };
}

/* -------------------------------------------------------------------------- */
/* Component                                                                  */
/* -------------------------------------------------------------------------- */

type Props = {
  /** Optional: render a custom trigger instead of the default button. */
  trigger?: React.ReactNode;
  /** Called after a successful create or launch. */
  onCreated?: (campaignId: string) => void;
  /** Called after a successful draft save. */
  onDraftSaved?: () => void;
};

export default function CreateCampaignDialog({
  trigger,
  onCreated,
  onDraftSaved,
}: Props) {
  const [open, setOpen] = useState(false);
  const [playbooks, setPlaybooks] = useState<PlaybookSummary[]>([]);
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);
  const [loadingRefs, setLoadingRefs] = useState(false);
  const [submitting, setSubmitting] = useState<"draft" | "launch" | null>(null);
  const refsLoadedRef = useRef(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(launchSchema) as unknown as import("react-hook-form").Resolver<FormValues>,
    mode: "onBlur",
    defaultValues: defaultDraft() as unknown as FormValues,
  });

  const { control, register, reset, setValue, formState, getValues } = form;
  const { errors } = formState;

  const startImmediately = useWatch({
    control,
    name: "schedule.start_immediately",
  });

  const timezoneOptions = useMemo(() => {
    const local = resolveLocalTimezone();
    const set = new Set([local, ...CURATED_TIMEZONES]);
    return Array.from(set);
  }, []);

  /* Load reference data lazily, only the first time the dialog opens. */
  const loadRefs = useCallback(async () => {
    setLoadingRefs(true);
    try {
      const [pbs, lists] = await Promise.all([
        listPlaybooks(true).catch(() => listPlaybooks()),
        listLeadLists(),
      ]);
      setPlaybooks(pbs);
      setLeadLists(lists);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to load form data"
      );
    } finally {
      setLoadingRefs(false);
    }
  }, []);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next && !refsLoadedRef.current) {
      refsLoadedRef.current = true;
      void loadRefs();
    }
  }

  function resetAndClose() {
    reset(defaultDraft() as unknown as FormValues);
    setOpen(false);
  }

  async function handleSaveDraft() {
    const values = getValues();
    const trimmed = values.name?.trim() ?? "";
    if (trimmed.length < 2) {
      form.setError("name", {
        message: "Give your draft a name (min 2 chars)",
      });
      return;
    }
    setSubmitting("draft");
    try {
      upsertDraft({
        id: newDraftId(),
        saved_at: new Date().toISOString(),
        data: { ...values, name: trimmed } as CampaignDraft,
      });
      toast.success("Draft saved");
      onDraftSaved?.();
      resetAndClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save draft");
    } finally {
      setSubmitting(null);
    }
  }

  const handleLaunch = form.handleSubmit(async (values) => {
    setSubmitting("launch");
    try {
      const created = await createCampaign({
        ...(values as CampaignDraft),
        launch: true,
      });
      try {
        await activateCampaign(created.id);
        toast.success(`Campaign "${values.name}" launched`);
      } catch (activateErr) {
        toast.warning(
          `Campaign saved but launch failed: ${
            activateErr instanceof Error ? activateErr.message : "unknown error"
          }`
        );
      }
      onCreated?.(created.id);
      resetAndClose();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to create campaign"
      );
    } finally {
      setSubmitting(null);
    }
  });

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button className="bg-violet-600 hover:bg-violet-500 text-white">
            <Plus size={14} />
            New Campaign
          </Button>
        )}
      </DialogTrigger>

      <DialogContent className="sm:max-w-2xl p-0 gap-0 bg-[#0c0c10] border border-white/[0.08] ring-0">
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <div className="flex items-start gap-3">
            <div className="h-9 w-9 shrink-0 rounded-[10px] bg-violet-500/10 border border-violet-500/25 flex items-center justify-center">
              <Rocket size={16} className="text-violet-300" />
            </div>
            <div>
              <DialogTitle className="text-[15px] text-white">
                Create campaign
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/45 mt-0.5">
                Configure targeting, schedule, and calling hours. Save as
                draft anytime.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form
          onSubmit={handleLaunch}
          className="max-h-[70vh] overflow-y-auto px-5 py-5 space-y-6"
        >
          {/* --- Basics ------------------------------------------------- */}
          <Section
            icon={<Target size={13} />}
            title="Basics"
            hint="A name your team will recognize"
          >
            <FormField
              label="Campaign name"
              required
              error={errors.name?.message}
            >
              <Input
                placeholder="Q3 SaaS · Warm inbound"
                autoFocus
                className="h-9 bg-white/[0.03] border-white/[0.09]"
                {...register("name")}
              />
            </FormField>
          </Section>

          <Separator className="bg-white/[0.05]" />

          {/* --- Targeting ---------------------------------------------- */}
          <Section
            icon={<BookOpen size={13} />}
            title="Targeting"
            hint="Pick the playbook to follow and the list of leads to call"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <FormField
                label="Playbook"
                required
                error={errors.playbook_id?.message}
              >
                <Controller
                  control={control}
                  name="playbook_id"
                  render={({ field }) => (
                    <Select
                      value={field.value ?? undefined}
                      onValueChange={(v) => field.onChange(v)}
                      disabled={loadingRefs}
                    >
                      <SelectTrigger
                        className={cn(
                          "w-full h-9 bg-white/[0.03] border-white/[0.09] text-[13px]",
                          errors.playbook_id && "border-red-500/50"
                        )}
                      >
                        <SelectValue
                          placeholder={
                            loadingRefs ? "Loading…" : "Select a playbook"
                          }
                        />
                      </SelectTrigger>
                      <SelectContent
                        className="bg-[#111114] border-white/[0.08]"
                        position="popper"
                      >
                        {playbooks.length === 0 && !loadingRefs && (
                          <div className="px-3 py-6 text-[12px] text-white/45 text-center">
                            No playbooks yet — create one first.
                          </div>
                        )}
                        {playbooks.map((pb) => (
                          <SelectItem key={pb.id} value={pb.id}>
                            <div className="flex flex-col">
                              <span className="text-[13px]">{pb.name}</span>
                              <span className="text-[11px] text-white/40">
                                {pb.framework} · {pb.status} · v{pb.version}
                              </span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </FormField>

              <FormField
                label="Lead list"
                required
                error={errors.lead_list_id?.message}
              >
                <Controller
                  control={control}
                  name="lead_list_id"
                  render={({ field }) => (
                    <Select
                      value={field.value ?? undefined}
                      onValueChange={(v) => field.onChange(v)}
                      disabled={loadingRefs}
                    >
                      <SelectTrigger
                        className={cn(
                          "w-full h-9 bg-white/[0.03] border-white/[0.09] text-[13px]",
                          errors.lead_list_id && "border-red-500/50"
                        )}
                      >
                        <SelectValue
                          placeholder={
                            loadingRefs ? "Loading…" : "Select a lead list"
                          }
                        />
                      </SelectTrigger>
                      <SelectContent
                        className="bg-[#111114] border-white/[0.08]"
                        position="popper"
                      >
                        {leadLists.length === 0 && !loadingRefs && (
                          <div className="px-3 py-6 text-[12px] text-white/45 text-center">
                            No lead lists available.
                          </div>
                        )}
                        {leadLists.map((list) => (
                          <SelectItem key={list.id} value={list.id}>
                            <div className="flex items-center justify-between gap-3 w-full">
                              <div className="flex flex-col">
                                <span className="text-[13px]">{list.name}</span>
                                {list.source && (
                                  <span className="text-[11px] text-white/40">
                                    {list.source}
                                  </span>
                                )}
                              </div>
                              <span className="text-[11px] text-white/55 inline-flex items-center gap-1">
                                <Users size={10} />
                                {list.lead_count.toLocaleString()}
                              </span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </FormField>
            </div>

            {loadingRefs && (
              <div className="text-[11px] text-white/40 flex items-center gap-1.5">
                <Loader2 size={11} className="animate-spin" />
                Loading playbooks and lead lists…
              </div>
            )}
          </Section>

          <Separator className="bg-white/[0.05]" />

          {/* --- Schedule ----------------------------------------------- */}
          <Section
            icon={<CalendarClock size={13} />}
            title="Schedule"
            hint="When the campaign should start dialing"
          >
            <Controller
              control={control}
              name="schedule.start_immediately"
              render={({ field }) => (
                <label className="flex items-center justify-between rounded-[10px] border border-white/[0.07] bg-white/[0.02] px-3 py-2.5 cursor-pointer">
                  <div className="min-w-0">
                    <div className="text-[13px] text-white">
                      Start immediately
                    </div>
                    <div className="text-[11px] text-white/45 mt-0.5">
                      Begin dialing as soon as the campaign is launched
                    </div>
                  </div>
                  <Switch
                    checked={field.value}
                    onCheckedChange={(v) => {
                      field.onChange(v);
                      if (v) {
                        setValue("schedule.date", null, { shouldDirty: true });
                        setValue("schedule.time", null, { shouldDirty: true });
                      } else {
                        setValue("schedule.date", todayLocalISODate());
                        setValue("schedule.time", "09:00");
                      }
                    }}
                  />
                </label>
              )}
            />

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <FormField
                label="Start date"
                required={!startImmediately}
                error={errors.schedule?.date?.message}
              >
                <Input
                  type="date"
                  disabled={startImmediately}
                  min={todayLocalISODate()}
                  className="h-9 bg-white/[0.03] border-white/[0.09]"
                  {...register("schedule.date")}
                />
              </FormField>

              <FormField
                label="Start time"
                required={!startImmediately}
                error={errors.schedule?.time?.message}
              >
                <Input
                  type="time"
                  disabled={startImmediately}
                  className="h-9 bg-white/[0.03] border-white/[0.09]"
                  {...register("schedule.time")}
                />
              </FormField>

              <FormField
                label="Timezone"
                required
                error={errors.schedule?.timezone?.message}
              >
                <Controller
                  control={control}
                  name="schedule.timezone"
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                    >
                      <SelectTrigger className="w-full h-9 bg-white/[0.03] border-white/[0.09] text-[13px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent
                        className="bg-[#111114] border-white/[0.08] max-h-72"
                        position="popper"
                      >
                        {timezoneOptions.map((tz) => (
                          <SelectItem key={tz} value={tz}>
                            {tz}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </FormField>
            </div>
          </Section>

          <Separator className="bg-white/[0.05]" />

          {/* --- Business Hours ----------------------------------------- */}
          <Section
            icon={<Clock size={13} />}
            title="Business hours"
            hint="The agent will only place calls inside this window"
          >
            <FormField
              label="Calling days"
              required
              error={errors.business_hours?.days?.message as string | undefined}
            >
              <Controller
                control={control}
                name="business_hours.days"
                render={({ field }) => (
                  <DayPicker
                    value={field.value}
                    onChange={field.onChange}
                  />
                )}
              />
            </FormField>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <FormField
                label="Window start"
                required
                error={errors.business_hours?.start?.message}
              >
                <Input
                  type="time"
                  className="h-9 bg-white/[0.03] border-white/[0.09]"
                  {...register("business_hours.start")}
                />
              </FormField>
              <FormField
                label="Window end"
                required
                error={errors.business_hours?.end?.message}
              >
                <Input
                  type="time"
                  className="h-9 bg-white/[0.03] border-white/[0.09]"
                  {...register("business_hours.end")}
                />
              </FormField>
            </div>

            <Controller
              control={control}
              name="business_hours.skip_holidays"
              render={({ field }) => (
                <label className="flex items-center justify-between rounded-[10px] border border-white/[0.07] bg-white/[0.02] px-3 py-2.5 cursor-pointer">
                  <div>
                    <div className="text-[13px] text-white">
                      Skip national holidays
                    </div>
                    <div className="text-[11px] text-white/45 mt-0.5">
                      Pause dialing on observed public holidays in the
                      selected timezone
                    </div>
                  </div>
                  <Switch
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                </label>
              )}
            />
          </Section>
        </form>

        <div className="flex flex-col-reverse sm:flex-row sm:justify-between sm:items-center gap-2 px-5 py-3 border-t border-white/[0.06] bg-white/[0.015]">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-white/55 hover:text-white"
            onClick={resetAndClose}
            disabled={submitting !== null}
          >
            Cancel
          </Button>

          <div className="flex gap-2 sm:justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleSaveDraft}
              disabled={submitting !== null}
              className="border-white/[0.1] bg-white/[0.02] text-white/85 hover:bg-white/[0.06] hover:text-white"
            >
              {submitting === "draft" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Save size={13} />
              )}
              Save draft
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={handleLaunch}
              disabled={submitting !== null}
              className="bg-violet-600 hover:bg-violet-500 text-white"
            >
              {submitting === "launch" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Rocket size={13} />
              )}
              Launch campaign
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* -------------------------------------------------------------------------- */
/* Sub-components                                                             */
/* -------------------------------------------------------------------------- */

function Section({
  icon,
  title,
  hint,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-violet-300/90">{icon}</span>
        <h3 className="text-[12px] font-medium text-white/85 uppercase tracking-wider">
          {title}
        </h3>
      </div>
      {hint && (
        <p className="text-[11px] text-white/40 -mt-1 ml-[1.35rem]">{hint}</p>
      )}
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function FormField({
  label,
  required,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[11px] font-medium text-white/55">
        {label}
        {required && <span className="text-violet-300/80 ml-0.5">*</span>}
      </Label>
      {children}
      {error && (
        <p className="text-[11px] text-red-400/90 leading-tight">{error}</p>
      )}
    </div>
  );
}

function DayPicker({
  value,
  onChange,
}: {
  value: Weekday[];
  onChange: (next: Weekday[]) => void;
}) {
  function toggle(day: Weekday) {
    if (value.includes(day)) {
      onChange(value.filter((d) => d !== day));
    } else {
      // Preserve canonical Mon-Sun ordering.
      const order = WEEKDAYS.map((w) => w.id);
      const set = new Set([...value, day]);
      onChange(order.filter((d) => set.has(d)));
    }
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {WEEKDAYS.map((d) => {
        const active = value.includes(d.id);
        return (
          <button
            key={d.id}
            type="button"
            onClick={() => toggle(d.id)}
            className={cn(
              "h-8 min-w-[44px] px-2.5 rounded-[8px] text-[12px] font-medium transition-colors border",
              active
                ? "bg-violet-500/15 text-violet-200 border-violet-500/35"
                : "bg-white/[0.03] text-white/60 border-white/[0.08] hover:text-white hover:bg-white/[0.06]"
            )}
            aria-pressed={active}
          >
            {d.short}
          </button>
        );
      })}
    </div>
  );
}
