"use client";

import { useEffect, useState } from "react";
import { apiUrl, hostOf, type ExtractorData } from "@/lib/api";
import CopyButton from "./CopyButton";

export default function ResultPanel({
  slug,
  sourceUrl,
}: {
  slug: string;
  sourceUrl: string;
}) {
  const [payload, setPayload] = useState<ExtractorData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const endpointPath = `/api/${slug}`;
  const docsPath = `/api/${slug}/docs`;
  // Absolute URL the visitor can actually curl — resolved against the page origin.
  const [absEndpoint, setAbsEndpoint] = useState(endpointPath);

  useEffect(() => {
    setAbsEndpoint(new URL(endpointPath, window.location.origin).toString());
    fetch(apiUrl(endpointPath))
      .then((r) => r.json())
      .then(setPayload)
      .catch(() => setError("Could not load the live preview."));
  }, [endpointPath]);

  const curl = `curl ${absEndpoint}`;
  const preview = payload?.data?.slice(0, 8) ?? [];

  return (
    <div className="animate-rise rounded-xl border border-pulse/30 bg-panel/80 p-5 ring-pulse">
      <div className="mb-4 flex items-center gap-2">
        <span className="text-pulse">◉</span>
        <h2 className="font-display text-lg font-semibold text-bone">Your API is live</h2>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-pulse">
          <span aria-hidden>✓</span> robots.txt respected
        </span>
      </div>

      {/* endpoint */}
      <label className="mb-1 block text-[11px] uppercase tracking-widest text-ash">
        Endpoint
      </label>
      <div className="mb-4 flex items-center gap-2 rounded-lg border border-line bg-void/60 px-3 py-2">
        <span className="text-pulse">GET</span>
        <code className="min-w-0 flex-1 truncate text-data">{absEndpoint}</code>
        <CopyButton value={absEndpoint} />
      </div>

      {/* curl + docs */}
      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-line bg-void/60 p-3">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-widest text-ash">Try it</span>
            <CopyButton value={curl} label="copy curl" />
          </div>
          <code className="block overflow-x-auto whitespace-nowrap text-xs text-bone">
            {curl}
          </code>
        </div>
        <a
          href={apiUrl(docsPath)}
          target="_blank"
          rel="noreferrer"
          className="flex items-center justify-between rounded-lg border border-line bg-void/60 p-3 transition-colors hover:border-data/50"
        >
          <div>
            <div className="text-[11px] uppercase tracking-widest text-ash">Documentation</div>
            <div className="text-sm text-data">Swagger UI →</div>
          </div>
          <span className="text-2xl text-data/70">⌁</span>
        </a>
      </div>

      {/* live preview */}
      <div className="rounded-lg border border-line bg-void/60">
        <div className="flex items-center justify-between border-b border-line px-3 py-2">
          <span className="text-[11px] uppercase tracking-widest text-ash">
            Live response · {payload?.record_count ?? preview.length} records from{" "}
            {hostOf(sourceUrl)}
          </span>
          {payload && <CopyButton value={JSON.stringify(payload.data, null, 2)} label="copy json" />}
        </div>
        {error ? (
          <p className="p-3 text-sm text-flat">{error}</p>
        ) : (
          <pre className="max-h-72 overflow-auto p-3 text-xs leading-relaxed text-bone">
            {payload ? JSON.stringify(preview, null, 2) : "loading preview…"}
          </pre>
        )}
      </div>

      <p className="mt-3 text-xs text-ash">
        Cached and refreshed automatically. Source:{" "}
        <a href={sourceUrl} target="_blank" rel="noreferrer" className="text-ash underline hover:text-data">
          {hostOf(sourceUrl)}
        </a>
      </p>
    </div>
  );
}
