interface Props {
  label: string;
  value: string | number | null;
  sub?: string;
}

export default function StatCard({ label, value, sub }: Props) {
  return (
    <div className="bg-white border border-stone-200 rounded-lg px-4 py-3 shadow-sm">
      <p className="text-lg font-bold text-stone-900">
        {value === null ? "—" : typeof value === "number" ? value.toLocaleString() : value}
      </p>
      <p className="text-[10px] text-stone-400 mt-0.5">{label}</p>
      {sub && <p className="text-xs text-stone-400 mt-1">{sub}</p>}
    </div>
  );
}
