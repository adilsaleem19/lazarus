"use client";

import { useEffect, useRef } from "react";
import type { StreamEvent } from "@/lib/api";
import { phaseOf, TONE_TEXT, TONE_BORDER } from "@/lib/phases";

export default function EventLog({
  events,
  startedAt,
}: {
  events: StreamEvent[];
  startedAt: number;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  return (
    <div className="h-[42vh] min-h-[280px] overflow-y-auto rounded-xl border border-line bg-panel/70 p-4 font-mono text-sm leading-relaxed sm:h-[46vh]">
      {events.length === 0 && (
        <p className="text-ash">
          <span className="animate-blink text-pulse">▍</span> awaiting first vital sign…
        </p>
      )}
      <ol className="space-y-1.5">
        {events.map((e) => {
          const phase = phaseOf(e.kind);
          const t = Math.max(0, (new Date(e.at ?? Date.now()).getTime() - startedAt) / 1000);
          const elapsed = e.at ? t : 0;
          const err = typeof e.data?.error === "string" ? (e.data.error as string) : null;
          return (
            <li key={e.seq} className="animate-rise">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 w-12 shrink-0 text-right text-xs tabular-nums text-ash">
                  {e.at ? `+${elapsed.toFixed(1)}` : "·"}
                </span>
                <span
                  className={`mt-px shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-widest ${TONE_TEXT[phase.tone]} ${TONE_BORDER[phase.tone]}`}
                >
                  {phase.badge}
                </span>
                <div className="min-w-0">
                  <span className="text-bone">{e.message}</span>
                  {err && (
                    <pre className="mt-1 overflow-x-auto rounded border border-flat/30 bg-flat/5 px-2 py-1 text-xs text-flat">
                      {err}
                    </pre>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <div ref={endRef} />
    </div>
  );
}
