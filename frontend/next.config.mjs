/** @type {import('next').NextConfig} */
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8008";

const nextConfig = {
  // Emit a self-contained server bundle (.next/standalone) for a small Docker
  // production image. Ignored by `next dev`.
  output: "standalone",
  async rewrites() {
    // Proxy API calls to the FastAPI backend so the browser sees one origin
    // (keeps the session cookie first-party). NOTE: rewrites are resolved when
    // the server config is evaluated, so in Docker BACKEND_URL is provided as a
    // build arg (see frontend/Dockerfile) as well as at runtime.
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};

export default nextConfig;
