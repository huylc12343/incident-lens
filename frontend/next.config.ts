import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep development artifacts separate from production builds. Mixing both
  // in `.next` can leave stale RSC manifests and missing webpack chunks.
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
  experimental: {
    // The backend accepts a 250 MB video plus a 25 MB telemetry file. Leave
    // room for multipart boundaries while proxying the upload through Next.
    middlewareClientMaxBodySize: "300mb",
  },
  async rewrites() {
    const backendUrl = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
    return [
      {
        source: "/backend/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
