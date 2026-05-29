import Link from "next/link";

export default function ReportsIndexPage() {
  return (
    <div className="flex items-center justify-center flex-1">
      <div className="text-center">
        <p className="text-stone-400 mb-4 text-sm">No reports yet.</p>
        <Link
          href="/map"
          className="px-4 py-2 bg-amber-600 text-white text-sm font-semibold rounded-md hover:bg-amber-700 transition-colors"
        >
          Run your first analysis
        </Link>
      </div>
    </div>
  );
}
