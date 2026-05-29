import type { Tier } from "@/lib/types";

const TIER_STYLES: Record<Tier, string> = {
  A: "bg-amber-500/20 text-amber-400 border border-amber-500/40",
  B: "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40",
  C: "bg-blue-500/20 text-blue-400 border border-blue-500/40",
  D: "bg-slate-700/50 text-slate-400 border border-slate-600",
};

export default function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) return <span className="text-slate-600 text-xs">—</span>;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${TIER_STYLES[tier]}`}>
      {tier}
    </span>
  );
}
