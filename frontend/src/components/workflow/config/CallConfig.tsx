import { useEffect, useRef, useState } from "react";
import { Popover } from "radix-ui";
import { Check, ChevronsUpDown, Loader2, AlertCircle } from "lucide-react";

import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useAllPlaybooks } from "@/hooks/useAllPlaybooks";
import type { CallConfig } from "@/types/workflow";

interface Props {
  config: CallConfig;
  onChange: (next: CallConfig) => void;
}

export default function CallConfigPanel({ config, onChange }: Props) {
  const { playbooks, loading, error, reload } = useAllPlaybooks();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const filtered = playbooks.filter((pb) =>
    pb.name.toLowerCase().includes(search.toLowerCase())
  );

  const selected = playbooks.find((pb) => pb.id === config.playbook_id);

  // Focus search input when popover opens
  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 50);
    } else {
      setSearch("");
    }
  }, [open]);

  return (
    <div className="flex flex-col gap-5">
      {/* Playbook combobox */}
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">
          Playbook
        </Label>

        <Popover.Root open={open} onOpenChange={setOpen}>
          <Popover.Trigger asChild>
            <Button
              variant="outline"
              role="combobox"
              aria-expanded={open}
              className="w-full justify-between bg-white/5 border-white/10 text-white text-sm hover:bg-white/10 hover:text-white font-normal"
            >
              {loading && !selected ? (
                <span className="flex items-center gap-2 text-white/40">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Loading playbooks…
                </span>
              ) : selected ? (
                <span className="truncate">{selected.name}</span>
              ) : (
                <span className="text-white/40">Select a playbook…</span>
              )}
              <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 text-white/40" />
            </Button>
          </Popover.Trigger>

          <Popover.Portal>
            <Popover.Content
              className="z-50 w-[var(--radix-popover-trigger-width)] rounded-md border border-white/10 bg-[#1a1a2e] shadow-xl"
              sideOffset={4}
              align="start"
            >
              {/* Search input */}
              <div className="border-b border-white/10 p-2">
                <Input
                  ref={searchRef}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search playbooks…"
                  className="h-7 bg-white/5 border-white/10 text-white text-sm placeholder:text-white/30 focus-visible:ring-0 focus-visible:ring-offset-0"
                />
              </div>

              <div className="max-h-60 overflow-y-auto py-1">
                {/* Loading state */}
                {loading && (
                  <div className="flex items-center gap-2 px-3 py-2 text-white/40 text-sm">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Loading…
                  </div>
                )}

                {/* Error state */}
                {!loading && error && (
                  <div className="px-3 py-2">
                    <div className="flex items-start gap-2 text-red-400 text-sm mb-2">
                      <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                      <span>{error}</span>
                    </div>
                    <button
                      onClick={() => reload()}
                      className="text-xs text-white/50 hover:text-white/80 underline"
                    >
                      Try again
                    </button>
                  </div>
                )}

                {/* Empty state */}
                {!loading && !error && filtered.length === 0 && (
                  <div className="px-3 py-4 text-center text-sm text-white/40">
                    {search
                      ? "No playbooks match your search."
                      : "No playbooks found. Create one first."}
                  </div>
                )}

                {/* Playbook options */}
                {!loading &&
                  !error &&
                  filtered.map((pb) => (
                    <button
                      key={pb.id}
                      onClick={() => {
                        onChange({ ...config, playbook_id: pb.id });
                        setOpen(false);
                      }}
                      className="flex w-full items-center gap-2 px-3 py-2 text-sm text-white hover:bg-white/10 focus:bg-white/10 focus:outline-none"
                    >
                      <Check
                        className={`h-4 w-4 shrink-0 text-indigo-400 ${
                          pb.id === config.playbook_id
                            ? "opacity-100"
                            : "opacity-0"
                        }`}
                      />
                      <span className="flex-1 text-left truncate">{pb.name}</span>
                      <span className="text-[11px] text-white/30 capitalize shrink-0">
                        {pb.status}
                      </span>
                    </button>
                  ))}
              </div>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>

        {error && !open && (
          <p className="text-red-400/80 text-[11px]">
            Failed to load playbooks.{" "}
            <button
              onClick={() => reload()}
              className="underline hover:text-red-300"
            >
              Retry
            </button>
          </p>
        )}
      </div>

      {/* Retry count */}
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">
          Retry count
        </Label>
        <Input
          type="number"
          min={0}
          max={10}
          value={config.retry_count}
          onChange={(e) =>
            onChange({
              ...config,
              retry_count: Math.max(0, parseInt(e.target.value, 10) || 0),
            })
          }
          className="bg-white/5 border-white/10 text-white text-sm w-24"
        />
        <p className="text-white/30 text-[11px]">
          Number of retry attempts if the call fails.
        </p>
      </div>

      {/* Phone number override */}
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">
          Phone number override
        </Label>
        <Input
          type="tel"
          placeholder="e.g. +917541006707"
          value={config.to_number ?? ""}
          onChange={(e) =>
            onChange({
              ...config,
              to_number: e.target.value || undefined,
            })
          }
          className="bg-white/5 border-white/10 text-white text-sm placeholder:text-white/20"
        />
        <p className="text-white/30 text-[11px]">
          When set, this number is called instead of the lead&apos;s phone.
          Use E.164 format (e.g. +917541006707).
        </p>
      </div>
    </div>
  );
}
