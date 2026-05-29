"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/explore", label: "Explore" },
  { href: "/analyze", label: "Analyze" },
  { href: "/reports", label: "Reports" },
  { href: "/chat", label: "Chat" },
  { href: "/admin", label: "Admin" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="h-14 border-b border-slate-800 bg-slate-950 flex items-center px-6 gap-8 shrink-0">
      <Link href="/explore" className="flex items-center gap-2 mr-4">
        <span className="text-amber-400 text-lg">☀</span>
        <span className="text-slate-100 font-semibold tracking-wide text-sm">HELIO</span>
      </Link>
      {NAV_LINKS.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={href}
            className={`text-sm transition-colors ${
              active
                ? "text-amber-400 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
