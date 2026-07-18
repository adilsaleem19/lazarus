"use client";

import Ekg, { type VitalState } from "./Ekg";

const DEADLINE_S = 60; // the promise the timer races

const LABEL: Record<VitalState, string> = {
  idle: "STANDBY",
  running: "RESUSCITATING",
  done: "ALIVE",
  failed: "FLATLINE",
};

const ACCENT: Record<VitalState, string> = {
  idle: "text-ash",
  running: "text-pulse",
  done: "text-pulse",
  failed: "text-flat",
};

export default function Vitals({
  state,
  elapsedMs,
  host,
}: {
  state: VitalState;
  elapsedMs: number;
  host: string;
}) {
  const secs = elapsedMs / 1000;
  const pct = Math.min(100, (secs / DEADLINE_S) * 100);
  const overtime = secs > DEADLINE_S && state === "running";
  const barColor =
    state === "failed" ? "bg-flat" : overtime ? "bg-charge" : "bg-pulse";
  const timeColor =
    state === "failed" ? "text-flat" : overtime ? "text-charge" : "text-pulse";

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-4 ring-pulse/0 backdrop-blur">
      <div className="mb-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              state === "failed" ? "bg-flat" : state === "idle" ? "bg-ash" : "bg-pulse"
            } ${state === "running" ? "animate-glow" : ""}`}
          />
          <span className={`text-xs font-bold tracking-[0.2em] ${ACCENT[state]}`}>
            {LABEL[state]}
          </span>
          <span className="hidden text-xs text-ash sm:inline">· patient: {host}</span>
        </div>
        <div className={`font-mono text-2xl font-bold tabular-nums ${timeColor}`}>
          T+{secs.toFixed(1)}
          <span className="text-sm text-ash">s</span>
        </div>
      </div>

      <Ekg state={state} className="h-14 w-full" />

      <div className="mt-3">
        <div className="h-1 w-full overflow-hidden rounded-full bg-line">
          <div
            className={`h-full ${barColor} transition-[width] duration-500 ease-out`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="mt-1 flex justify-between text-[10px] uppercase tracking-widest text-ash">
          <span>0s</span>
          <span>{overtime ? "past the 60s promise" : "60s promise"}</span>
        </div>
      </div>
    </div>
  );
}
