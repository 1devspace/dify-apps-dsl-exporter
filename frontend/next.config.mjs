/** @type {import('next').NextConfig} */
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8008";

const nextConfig = {
  async rewrites() {
    // Proxy API calls to the FastAPI backend so the browser sees one origin
    // (keeps the session cookie first-party in local dev).
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};

export default nextConfig;
