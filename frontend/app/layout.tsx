import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "APIfy — turn any website into an API",
  description: "Paste a public URL, get a working documented REST API in ~60 seconds.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-zinc-950 text-zinc-100 font-mono min-h-screen">{children}</body>
    </html>
  );
}
