/** @type {import('next').NextConfig} */

// In production the frontend is served behind Caddy, which routes /api, /jobs,
// /gallery, /healthz straight to the API — these rewrites never fire there.
// They exist so `npm run dev` on its own can still reach the backend same-origin.
const backend = process.env.BACKEND_ORIGIN || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/jobs/:path*", destination: `${backend}/jobs/:path*` },
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/healthz", destination: `${backend}/healthz` },
    ];
  },
};

export default nextConfig;
