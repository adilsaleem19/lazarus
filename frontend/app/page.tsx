import Link from "next/link";
import Ekg from "@/components/Ekg";
import UrlForm from "@/components/UrlForm";
import GalleryStrip from "@/components/GalleryStrip";

const STEPS = [
  { n: "01", t: "Read the page", d: "Loads it in a real browser, watches the network, distills the DOM." },
  { n: "02", t: "Write the scraper", d: "Picks a hidden JSON API or the HTML, then generates an extractor." },
  { n: "03", t: "Test & self-repair", d: "Runs it sandboxed, and rewrites its own code when a test fails." },
  { n: "04", t: "Serve it live", d: "Publishes a cached, documented, auto-refreshing REST endpoint." },
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col px-4">
      <header className="flex items-center justify-between py-6">
        <span className="flex items-center gap-2">
          <span className="text-pulse">✚</span>
          <span className="font-display font-semibold tracking-tight">LAZARUS</span>
        </span>
        <Link href="/gallery" className="text-sm text-ash hover:text-bone">
          gallery
        </Link>
      </header>

      <section className="flex flex-col items-center gap-6 pt-6 text-center sm:pt-14">
        <p className="text-xs uppercase tracking-[0.32em] text-ash">
          Autonomous web-to-API agent
        </p>
        <h1 className="font-display text-4xl font-bold leading-[1.05] tracking-tight sm:text-6xl">
          Raise a <span className="text-pulse text-glow-pulse">living API</span>
          <br />
          from any web page.
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-ash sm:text-base">
          Paste a public URL. An agent reads the page, writes a scraper, tests it, repairs its
          own mistakes, and hands you a documented REST API — in about a minute.
        </p>

        <div className="mt-2 w-full max-w-xl">
          <UrlForm />
        </div>
      </section>

      {/* idle monitor — the flatline waiting for a patient */}
      <div className="mt-10 w-full">
        <Ekg state="idle" className="h-10 w-full opacity-70" />
        <p className="mt-1 text-center text-[10px] uppercase tracking-[0.3em] text-ash/70">
          monitor idle — awaiting a patient
        </p>
      </div>

      <section className="mt-12 w-full">
        <ol className="grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2">
          {STEPS.map((s) => (
            <li key={s.n} className="bg-panel/60 p-4">
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-xs text-pulse">{s.n}</span>
                <h3 className="font-display font-semibold text-bone">{s.t}</h3>
              </div>
              <p className="mt-1 pl-8 text-sm text-ash">{s.d}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-12 w-full">
        <GalleryStrip />
      </section>

      <footer className="mt-auto flex items-center justify-between gap-4 py-8 text-xs text-ash">
        <span>Respects robots.txt · public data only · rate-limited</span>
        <a
          href="https://github.com/adilsaleem19/lazarus"
          target="_blank"
          rel="noreferrer"
          className="hover:text-bone"
        >
          source ↗
        </a>
      </footer>
    </main>
  );
}
