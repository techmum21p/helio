interface Props {
  label: string;
  value: string | number | null;
  sub?: string;
}

export default function StatCard({ label, value, sub }: Props) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-4">
      <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-2xl font-semibold text-slate-100 tabular-nums">
        {value === null ? "—" : typeof value === "number" ? value.toLocaleString() : value}
      </p>
      {sub && <p className="text-xs text-slate-600 mt-1">{sub}</p>}
    </div>
  );
}
