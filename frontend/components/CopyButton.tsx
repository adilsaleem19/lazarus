"use client";

import { useState } from "react";

export default function CopyButton({
  value,
  label = "copy",
  className = "",
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked (insecure origin) — the value is still selectable */
    }
  }

  return (
    <button
      onClick={copy}
      className={`shrink-0 rounded border border-line px-2.5 py-1 text-xs font-medium transition-colors hover:border-pulse/50 hover:text-pulse focus-visible:outline focus-visible:outline-2 focus-visible:outline-pulse ${copied ? "text-pulse" : "text-ash"} ${className}`}
    >
      {copied ? "copied ✓" : label}
    </button>
  );
}
