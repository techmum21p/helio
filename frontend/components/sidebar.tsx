"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import type { Run } from "@/lib/types";
import { getRuns } from "@/lib/api";
import SidebarPipelineCard from "./sidebar-pipeline-card";

const NAV_LINKS = [
  { href: "/map",     icon: "🗺",  label: "Map & Scores" },
  { href: "/explore", icon: "🔍",  label: "Explore"      },
  { href: "/reports", icon: "📄",  label: "Reports"      },
  { href: "/chat",    icon: "💬",  label: "Chat"         },
  { href: "/admin",   icon: "⚙️",  label: "Admin"        },
];

interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

export default function Sidebar({ collapsed, onToggle }: Props) {
  const pathname = usePathname();
  const { data: runs = [] } = useSWR<Run[]>("runs-1", () => getRuns(1));
  const lastRun = runs[0] ?? null;

  return (
    <aside
      className="flex flex-col shrink-0 border-r border-stone-200 bg-stone-100 transition-all duration-200 overflow-hidden"
      style={{ width: collapsed ? 56 : 228 }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-3.5 py-4 border-b border-stone-200 shrink-0">
        <span className="text-lg shrink-0">☀️</span>
        {!collapsed && (
          <span className="text-xs font-black tracking-[0.2em] text-stone-900 whitespace-nowrap">
            HELIO
          </span>
        )}
      </div>

      {/* Collapse toggle */}
      <div className="px-2 pt-2 shrink-0">
        <button
          onClick={onToggle}
          className="w-full flex items-center justify-center gap-1.5 border border-stone-300 rounded-md py-1.5 text-xs text-stone-500 hover:bg-stone-200 transition-colors"
        >
          <span>{collapsed ? "▶" : "◀"}</span>
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>

      {/* Nav links */}
      <nav className="flex flex-col gap-0.5 px-2 py-2 shrink-0">
        {NAV_LINKS.map(({ href, icon, label }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition-colors ${
                active
                  ? "bg-amber-50 border border-amber-200/70 text-amber-800 font-semibold"
                  : "text-stone-600 hover:bg-stone-200"
              }`}
            >
              <span className="text-sm shrink-0">{icon}</span>
              {!collapsed && <span className="whitespace-nowrap">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Scrollable bottom area: last-run badge + pipeline card */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-2 px-2 pb-3 min-h-0">
        {!collapsed && lastRun && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 shrink-0">
            <p className="text-[10px] text-stone-400 uppercase tracking-wide mb-0.5">Last run</p>
            <p className="text-xs font-semibold text-amber-900 truncate">{lastRun.location}</p>
            <p className="text-[10px] text-amber-700 mt-0.5">
              {lastRun.status === "done" ? "✓ Completed" : lastRun.status}
            </p>
          </div>
        )}

        {!collapsed && <SidebarPipelineCard />}
      </div>
    </aside>
  );
}
