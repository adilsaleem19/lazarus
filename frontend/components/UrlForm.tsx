"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createJob } from "@/lib/api";
import { pickDemoSite } from "@/lib/demo";

export default function UrlForm() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const isDemo = new URLSearchParams(window.location.search).get("demo") === "1";
    if (isDemo) {
      setDemo(true);
      setUrl(pickDemoSite());
      setAgreed(true);
    }
    inputRef.current?.focus();
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!url.trim()) return setError("Paste a URL first.");
    if (!agreed) return setError("Please confirm responsible use to continue.");
    setSubmitting(true);
    try {
      const { id } = await createJob(url.trim());
      router.push(`/watch/${id}${demo ? "?demo=1" : ""}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="w-full">
      <div
        className={`flex items-center gap-2 rounded-xl border bg-panel/70 px-3 py-2.5 backdrop-blur transition-shadow ${
          submitting ? "border-pulse/40 ring-pulse" : "border-line focus-within:border-pulse/40 focus-within:ring-pulse"
        }`}
      >
        <span className="select-none pl-1 text-pulse">▸</span>
        <input
          ref={inputRef}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={submitting}
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="https://any-public-page.com"
          className="min-w-0 flex-1 bg-transparent py-1 text-bone placeholder:text-ash/60 focus:outline-none"
        />
        <button
          type="submit"
          disabled={submitting}
          className="shrink-0 rounded-lg bg-pulse px-4 py-2 text-sm font-bold text-void transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {submitting ? "raising…" : "Resurrect →"}
        </button>
      </div>

      <label className="mt-3 flex cursor-pointer items-start gap-2.5 text-sm text-ash">
        <input
          type="checkbox"
          checked={agreed}
          onChange={(e) => setAgreed(e.target.checked)}
          className="mt-0.5 h-4 w-4 shrink-0 accent-pulse"
        />
        <span>
          I&apos;ll use this responsibly — only public, non-personal data, respecting the
          target site&apos;s terms and robots.txt.
        </span>
      </label>

      {error && <p className="mt-2 text-sm text-flat">{error}</p>}
    </form>
  );
}
