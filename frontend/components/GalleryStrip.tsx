"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiUrl, GALLERY_PATH, hostOf, sinceLabel, type GalleryApi } from "@/lib/api";

// A compact "recently revived" strip for the landing page.
export default function GalleryStrip() {
  const [apis, setApis] = useState<GalleryApi[] | null>(null);

  useEffect(() => {
    fetch(apiUrl(GALLERY_PATH))
      .then((r) => r.json())
      .then((b) => setApis(b.apis))
      .catch(() => setApis([]));
  }, []);

  if (!apis || apis.length === 0) return null;

  return (
    <section className="w-full">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-xs uppercase tracking-[0.25em] text-ash">Recently revived</h2>
        <Link href="/gallery" className="text-xs text-data hover:underline">
          full gallery →
        </Link>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {apis.slice(0, 3).map((a) => (
          <a
            key={a.slug}
            href={apiUrl(a.endpoint)}
            target="_blank"
            rel="noreferrer"
            className="group rounded-lg border border-line bg-panel/50 p-3 transition-colors hover:border-pulse/40"
          >
            <div className="flex items-center gap-1.5 text-pulse">
              <span className="h-1.5 w-1.5 rounded-full bg-pulse" />
              <span className="truncate text-sm text-bone group-hover:text-pulse">
                {hostOf(a.source_url)}
              </span>
            </div>
            <div className="mt-1 text-xs text-ash">
              {a.record_count} records · {sinceLabel(a.last_refreshed)}
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
