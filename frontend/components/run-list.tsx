"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Run } from "@/lib/types";

const STATUS_STYLES = {
  done:    "bg-emerald-100 text-emerald-700",
  running: "bg-amber-100 text-amber-700",
  pending: "bg-stone-100 text-stone-500",
  failed:  "bg-red-100 text-red-600",
};

interface Props {
  runs: Run[];
  basePath?: string;
}

export default function RunList({ runs, basePath = "/reports" }: Props) {
  const pathname = usePathname();

  if (runs.length === 0) {
    return (
      <div className="p-4 text-stone-400 text-xs">
        No runs yet.{" "}
        <Link href="/analyze" className="text-amber-600 hover:underline">Run an analysis</Link>
      </div>
    );
  }

  return (
    <div className="divide-y divide-stone-100">
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
            className={`block px-3 py-3 transition-colors hover:bg-stone-50 ${
              active ? "bg-amber-50 border-l-2 border-amber-500" : ""
            }`}
          >
            <p className="text-xs text-stone-700 font-medium leading-snug line-clamp-2">{run.location}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-stone-400 text-xs">{date}</span>
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
