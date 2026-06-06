import { StopCircle } from "lucide-react";

export default function StopConfigPanel() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-8 text-center">
      <StopCircle size={32} className="text-rose-400/60" />
      <p className="text-white/50 text-sm">Terminal node</p>
      <p className="text-white/30 text-xs max-w-[200px]">
        STOP ends the workflow for this contact. No configuration required.
      </p>
    </div>
  );
}
