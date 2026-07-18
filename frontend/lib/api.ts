// Same-origin by default (served behind Caddy in prod, Next rewrites in dev).
// Override with NEXT_PUBLIC_API_BASE only for a fully separate API host.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export interface StreamEvent {
  seq: number;
  kind: string;
  message: string;
  data: Record<string, unknown>;
  at: string | null;
}

export interface GalleryApi {
  slug: string;
  endpoint: string;
  docs: string;
  source_url: string;
  description: string;
  strategy: string;
  version: number;
  record_count: number;
  last_refreshed: string | null;
  created_at: string;
}

export interface ExtractorData {
  slug: string;
  source_url: string;
  description: string;
  status: string;
  paused_reason: string | null;
  record_count: number;
  last_refreshed: string | null;
  attribution: string;
  data: Record<string, unknown>[];
}

export async function createJob(url: string): Promise<{ id: string }> {
  const res = await fetch(apiUrl("/jobs"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, responsible_use: true }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const GALLERY_PATH = "/api/gallery";

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function sinceLabel(iso: string | null): string {
  if (!iso) return "never";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 90) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}
