// Demo mode (?demo=1) never fakes events — it just curates targets known to work
// well on camera, and slows the *display* pacing so the stream is legible on video.
export const DEMO_SITES = [
  "https://books.toscrape.com/",
  "https://news.ycombinator.com/",
  "https://quotes.toscrape.com/",
];

export function pickDemoSite(): string {
  return DEMO_SITES[Math.floor(Math.random() * DEMO_SITES.length)];
}

// Minimum gap between revealing successive events, in ms.
export const DEMO_REVEAL_GAP = 750;
export const LIVE_REVEAL_GAP = 0;
