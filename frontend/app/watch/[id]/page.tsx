"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { apiUrl, hostOf, type StreamEvent } from "@/lib/api";
import { TERMINAL_KINDS } from "@/lib/phases";
import { DEMO_REVEAL_GAP, LIVE_REVEAL_GAP } from "@/lib/demo";
import Vitals from "@/components/Vitals";
import EventLog from "@/components/EventLog";
import ResultPanel from "@/components/ResultPanel";
import type { VitalState } from "@/components/Ekg";

export default function TheaterPage({ params }: { params: { id: string } }) {
  const jobId = params.id;
  const [sourceUrl, setSourceUrl] = useState<string>("");
  const [notFound, setNotFound] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  const buffer = useRef<Map<number, StreamEvent>>(new Map());
  const [visible, setVisible] = useState<StreamEvent[]>([]);
  const [startedAt, setStartedAt] = useState<number>(() => Date.now());
  const [elapsedMs, setElapsedMs] = useState(0);
  const demoRef = useRef(false);

  // Fetch the job once for its source URL + a not-found guard.
  useEffect(() => {
    demoRef.current = new URLSearchParams(window.location.search).get("demo") === "1";
    fetch(apiUrl(`/jobs/${jobId}`))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((j) => setSourceUrl(j.url))
      .catch(() => setNotFound(true));
  }, [jobId]);

  // Open the event stream; buffer by seq, then reveal (paced in demo mode).
  useEffect(() => {
    const es = new EventSource(apiUrl(`/jobs/${jobId}/events`));
    let closed = false;
    let revealTimer: ReturnType<typeof setTimeout> | null = null;

    const reveal = () => {
      const sorted = Array.from(buffer.current.values()).sort((a, b) => a.seq - b.seq);
      setVisible((prev) => {
        if (prev.length >= sorted.length) return prev;
        const next = sorted.slice(0, prev.length + 1);
        const last = next[next.length - 1];
        if (TERMINAL_KINDS.has(last.kind)) {
          closed = true;
          es.close();
        }
        return next;
      });
      const gap = demoRef.current ? DEMO_REVEAL_GAP : LIVE_REVEAL_GAP;
      revealTimer = setTimeout(reveal, gap);
    };

    es.onmessage = (msg) => {
      setReconnecting(false);
      try {
        const ev = JSON.parse(msg.data) as StreamEvent;
        if (!buffer.current.has(ev.seq)) buffer.current.set(ev.seq, ev);
      } catch {
        /* ignore keepalives / malformed frames */
      }
    };
    es.onerror = () => {
      if (!closed) setReconnecting(true);
    };

    reveal();
    return () => {
      es.close();
      if (revealTimer) clearTimeout(revealTimer);
    };
  }, [jobId]);

  // Anchor the clock to the first event's server time so T+ is honest.
  useEffect(() => {
    const first = visible[0];
    if (first?.at) setStartedAt(new Date(first.at).getTime());
  }, [visible]);

  const terminal = visible.find((e) => TERMINAL_KINDS.has(e.kind));
  const liveEvent = visible.find((e) => e.kind === "live");
  const failedEvent = visible.find((e) => e.kind === "failed");

  const state: VitalState = failedEvent
    ? "failed"
    : liveEvent
      ? "done"
      : visible.length > 0
        ? "running"
        : "idle";

  // Tick the timer while running; freeze at the terminal event's time.
  useEffect(() => {
    if (terminal) {
      const end = terminal.at ? new Date(terminal.at).getTime() : Date.now();
      setElapsedMs(Math.max(0, end - startedAt));
      return;
    }
    const id = setInterval(() => setElapsedMs(Math.max(0, Date.now() - startedAt)), 100);
    return () => clearInterval(id);
  }, [terminal, startedAt]);

  const host = useMemo(() => (sourceUrl ? hostOf(sourceUrl) : "unknown"), [sourceUrl]);

  if (notFound) {
    return (
      <Centered>
        <p className="text-flat">That job doesn&apos;t exist.</p>
        <Link href="/" className="text-data underline">
          Start a new one →
        </Link>
      </Centered>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-4 px-4 py-6 sm:py-10">
      <header className="flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 text-sm text-ash hover:text-bone">
          <span className="text-pulse">✚</span>
          <span className="font-display font-semibold tracking-tight text-bone">LAZARUS</span>
        </Link>
        <div className="flex items-center gap-3">
          {reconnecting && !terminal && (
            <span className="animate-blink text-xs text-charge">reconnecting…</span>
          )}
          {demoRef.current && (
            <span className="rounded border border-data/40 px-2 py-0.5 text-[10px] uppercase tracking-widest text-data">
              demo
            </span>
          )}
        </div>
      </header>

      <Vitals state={state} elapsedMs={elapsedMs} host={host} />

      <EventLog events={visible} startedAt={startedAt} />

      {liveEvent && <ResultPanel slug={String(liveEvent.data.slug)} sourceUrl={sourceUrl} />}

      {failedEvent && (
        <div className="animate-rise rounded-xl border border-flat/30 bg-flat/5 p-5">
          <h2 className="mb-1 font-display text-lg font-semibold text-flat">
            Couldn&apos;t revive this one
          </h2>
          <p className="text-sm text-bone">{failedEvent.message}</p>
          <Link
            href="/"
            className="mt-4 inline-block rounded border border-line px-3 py-1.5 text-sm text-data hover:border-data/50"
          >
            Try another page →
          </Link>
        </div>
      )}
    </main>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 p-8 text-center">
      {children}
    </main>
  );
}
