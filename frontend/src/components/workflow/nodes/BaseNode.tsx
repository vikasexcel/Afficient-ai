/**
 * Shared structural wrapper for workflow node cards.
 * Callers supply explicit headerClass/borderClass so Tailwind's class scanner
 * can detect every class statically (no dynamic concatenation).
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface BaseNodeProps {
  /** Content placed in the coloured header row (icon + title). */
  header: ReactNode;
  /** CSS class(es) applied to the header row div. */
  headerClass: string;
  /** CSS class(es) applied to the outer border. */
  borderClass: string;
  /** Short descriptive text shown in the body, if any. */
  label?: string;
  selected?: boolean;
  /** Additional content beneath the label. */
  children?: ReactNode;
}

export default function BaseNode({
  header,
  headerClass,
  borderClass,
  label,
  selected,
  children,
}: BaseNodeProps) {
  return (
    <div
      className={cn(
        "min-w-[160px] max-w-[210px] rounded-xl border-2 bg-[#12121a] shadow-lg",
        borderClass,
        selected && "ring-2 ring-white/40 shadow-2xl"
      )}
    >
      <div className={cn("flex items-center gap-2 rounded-t-[10px] px-3 py-2", headerClass)}>
        {header}
      </div>
      {(label || children) && (
        <div className="px-3 py-2">
          {label && (
            <p className="text-[12px] text-white/60 truncate">{label}</p>
          )}
          {children}
        </div>
      )}
    </div>
  );
}
