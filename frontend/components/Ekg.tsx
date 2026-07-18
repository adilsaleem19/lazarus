"use client";

// The signature element: an EKG trace whose state mirrors the job's vitals.
// idle = faint flatline, running/done = heartbeat, failed = red flatline.

export type VitalState = "idle" | "running" | "done" | "failed";

const TILE = 160;
const TILES = 16;
const BASE = 20;

function heartbeatPath(): string {
  let d = `M 0 ${BASE}`;
  for (let i = 0; i < TILES; i++) {
    const x = i * TILE;
    d +=
      ` L ${x + 66} ${BASE}` + // flat
      ` L ${x + 74} ${BASE - 4} L ${x + 82} ${BASE}` + // p-wave
      ` L ${x + 96} ${BASE}` +
      ` L ${x + 100} ${BASE + 5} L ${x + 108} ${BASE - 15} L ${x + 116} ${BASE + 8} L ${x + 122} ${BASE}` + // QRS
      ` L ${x + TILE} ${BASE}`; // flat to next tile
  }
  return d;
}

function flatPath(): string {
  return `M 0 ${BASE} L ${TILE * TILES} ${BASE}`;
}

const COLOR: Record<VitalState, string> = {
  idle: "#7C8A91",
  running: "#34E5A1",
  done: "#34E5A1",
  failed: "#FF5A6A",
};

export default function Ekg({ state, className = "" }: { state: VitalState; className?: string }) {
  const alive = state === "running" || state === "done";
  const d = alive ? heartbeatPath() : flatPath();
  const color = COLOR[state];
  const speed = state === "running" ? "animate-scan-fast" : "animate-scan-slow";

  return (
    <div className={`relative overflow-hidden ${className}`} aria-hidden>
      <div className={`h-full w-[200%] ${speed}`}>
        <svg
          viewBox={`0 0 ${TILE * TILES} 40`}
          preserveAspectRatio="none"
          className="h-full w-full"
        >
          <path
            d={d}
            fill="none"
            stroke={color}
            strokeWidth={1.6}
            strokeLinejoin="round"
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 6px ${color}${alive ? "88" : "33"})` }}
          />
        </svg>
      </div>
      {/* leading fade so the trace emerges from the dark like a real monitor sweep */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-void to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-void to-transparent" />
    </div>
  );
}
