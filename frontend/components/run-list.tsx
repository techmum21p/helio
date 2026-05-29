"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Run } from "@/lib/types";

const STATUS_STYLES = {
  done:    "bg-emerald-500/20 text-emerald-400",
  running: "bg-amber-500/20 text-amber-400",
  pending: "bg-slate-700 text-slate-400",
  failed:  "bg-red-500/20 text-red-400",
};

interface Props {
  runs: Run[];
  basePath?: string;
}

export default function RunList({ runs, basePath = "/reports" }: Props) {
  const pathname = usePathname();

  if (runs.length === 0) {
    return (
      <div className="p-4 text-slate-600 text-xs">
        No runs yet.{" "}
        <Link href="/analyze" className="text-amber-500 hover:underline">Run an analysis</Link>
      </div>
    );
  }

  return (
    <div className="divide-y divide-slate-800">
      {runs.map((run) => {
        const href = `${basePath}/${run.id}`;
        const active = pathname === href;
        const date = new Date(run.created_at).toLocaleDateString("en-PH", {
          month: "short", day: "numeric",
        });
        return (
          <Link
            key={run.id}
            href={href}
            className={`block px-3 py-3 transition-colors hover:bg-slate-900 ${
              active ? "bg-slate-900 border-l-2 border-amber-500" : ""
            }`}
          >
            <p className="text-xs text-slate-300 font-medium leading-snug line-clamp-2">{run.location}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-slate-600 text-xs">{date}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_STYLES[run.status]}`}>
                {run.status}
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
