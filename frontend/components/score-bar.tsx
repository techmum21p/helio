interface ScoreBarProps {
  solar: number | null;
  income: number | null;
  popDensity: number | null;
  showLabels?: boolean;
}

export default function ScoreBar({ solar, income, popDensity, showLabels = false }: ScoreBarProps) {
  const s = solar ?? 0;
  const i = income ?? 0;
  const p = popDensity ?? 0;

  return (
    <div className="w-full space-y-1">
      <div className="flex items-center gap-2">
        {showLabels && <span className="text-xs text-slate-500 w-12 shrink-0">Solar</span>}
        <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-blue-400 rounded-full" style={{ width: `${s * 100}%` }} />
        </div>
        {showLabels && <span className="text-xs text-blue-400 w-8 text-right">{s.toFixed(2)}</span>}
      </div>
      <div className="flex items-center gap-2">
        {showLabels && <span className="text-xs text-slate-500 w-12 shrink-0">Income</span>}
        <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-emerald-400 rounded-full" style={{ width: `${i * 100}%` }} />
        </div>
        {showLabels && <span className="text-xs text-emerald-400 w-8 text-right">{i.toFixed(2)}</span>}
      </div>
      <div className="flex items-center gap-2">
        {showLabels && <span className="text-xs text-slate-500 w-12 shrink-0">Pop</span>}
        <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-violet-400 rounded-full" style={{ width: `${p * 100}%` }} />
        </div>
        {showLabels && <span className="text-xs text-violet-400 w-8 text-right">{p.toFixed(2)}</span>}
      </div>
    </div>
  );
}
