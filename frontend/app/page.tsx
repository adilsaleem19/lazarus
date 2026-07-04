"use client";

import { useEffect, useState } from "react";

export default function Home() {
  const [backend, setBackend] = useState<"checking" | "online" | "offline">("checking");

  useEffect(() => {
    // works when served behind Caddy (same origin); Phase 4 builds the real UI
    fetch("/healthz")
      .then((r) => setBackend(r.ok ? "online" : "offline"))
      .catch(() => setBackend("offline"));
  }, []);

  const dot =
    backend === "online"
      ? "bg-emerald-400"
      : backend === "offline"
        ? "bg-red-500"
        : "bg-yellow-400";

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-4xl font-bold tracking-tight">
        API<span className="text-emerald-400">fy</span>
      </h1>
      <p className="text-zinc-400 text-center max-w-md">
        Autonomous website-to-API agent. Phase 1: ingestion engine.
        <br />
        The real interface arrives in Phase 4.
      </p>
      <div className="flex items-center gap-2 rounded border border-zinc-800 px-4 py-2 text-sm">
        <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
        backend: {backend}
      </div>
    </main>
  );
}
