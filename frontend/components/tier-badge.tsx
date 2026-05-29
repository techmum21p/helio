import type { Tier } from "@/lib/types";

const TIER_STYLES: Record<Tier, string> = {
  A: "bg-amber-100 text-amber-800 border border-amber-200",
  B: "bg-emerald-100 text-emerald-800 border border-emerald-200",
  C: "bg-blue-100 text-blue-700 border border-blue-200",
  D: "bg-stone-100 text-stone-500 border border-stone-200",
};

export default function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) return <span className="text-stone-400 text-xs">—</span>;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${TIER_STYLES[tier]}`}>
      {tier}
    </span>
  );
}
