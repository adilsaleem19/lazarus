// Maps each backend event kind to how the theater renders it: a short badge, a
// tone (which drives colour), and whether it ends the stream.

export type Tone = "idle" | "work" | "good" | "warn" | "bad";

interface PhaseMeta {
  badge: string;
  tone: Tone;
}

const PHASES: Record<string, PhaseMeta> = {
  analyzing: { badge: "WAKE", tone: "work" },
  robots_ok: { badge: "ROBOTS", tone: "good" },
  captured: { badge: "READ", tone: "work" },
  captured_only: { badge: "STOP", tone: "warn" },
  strategy_chosen: { badge: "PLAN", tone: "work" },
  code_generated: { badge: "WRITE", tone: "work" },
  test_failed: { badge: "TEST", tone: "warn" },
  repair_attempt: { badge: "REPAIR", tone: "warn" },
  validated: { badge: "VALID", tone: "good" },
  live: { badge: "LIVE", tone: "good" },
  failed: { badge: "FLATLINE", tone: "bad" },
};

export function phaseOf(kind: string): PhaseMeta {
  return PHASES[kind] ?? { badge: kind.slice(0, 6).toUpperCase(), tone: "work" };
}

export const TERMINAL_KINDS = new Set(["live", "failed", "captured_only"]);

export const TONE_TEXT: Record<Tone, string> = {
  idle: "text-ash",
  work: "text-data",
  good: "text-pulse",
  warn: "text-charge",
  bad: "text-flat",
};

export const TONE_BORDER: Record<Tone, string> = {
  idle: "border-line",
  work: "border-data/40",
  good: "border-pulse/40",
  warn: "border-charge/40",
  bad: "border-flat/40",
};
