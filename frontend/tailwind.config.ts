import type { Config } from "tailwindcss";

// Life-support monitor palette: a dead page is revived into a living API.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#07090B", // monitor off-state, cold near-black
        panel: "#0E1417", // raised terminal surface
        line: "#1C262B", // hairline borders
        pulse: "#34E5A1", // resuscitation green — the "alive" signal
        data: "#6BD6FF", // clinical cyan — data + links
        charge: "#F5A524", // amber — thinking / charging
        flat: "#FF5A6A", // flatline red — failure
        ash: "#7C8A91", // muted secondary text
        bone: "#DCE7EA", // primary text, slightly cool white
      },
      fontFamily: {
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      keyframes: {
        scan: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        blink: { "0%,49%": { opacity: "1" }, "50%,100%": { opacity: "0.15" } },
        rise: {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        glow: { "0%,100%": { opacity: "0.55" }, "50%": { opacity: "1" } },
      },
      animation: {
        "scan-fast": "scan 2.2s linear infinite",
        "scan-slow": "scan 6s linear infinite",
        blink: "blink 1.1s step-end infinite",
        rise: "rise 0.28s ease-out both",
        glow: "glow 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
