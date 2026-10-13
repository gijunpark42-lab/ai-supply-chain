const NEWS_DATA = [
  "./public/data/merged_graph.json",
  "./public/data/company_ko.json",
  "./public/data/i18n/company_names.json",
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Strict mode double-mounts components in dev, which tears down and rebuilds
  // the WebGL context and can blank the force graph. Off for a stable canvas.
  reactStrictMode: false,
  // react-force-graph pulls in three.js; nothing special needed, but keep
  // transpilePackages ready in case a nested ESM dep needs it.
  eslint: { ignoreDuringBuilds: true },
  experimental: {
    // One shared copy of @vercel/functions for every route, so the Runtime Cache the
    // /news ingest job writes and /api/news reads is the same store in `next dev`
    // too (its local stand-in lives in that module's memory).
    serverComponentsExternalPackages: ["@vercel/functions"],
    // /api/ask reads the graph from disk for its lookups (lib/askAgent.ts), and
    // /api/news*, /api/filings and /api/top read it + the local-name files (lib/news.ts);
    // ship the files with those functions on Vercel.
    outputFileTracingIncludes: {
      "/api/ask": ["./public/data/merged_graph.json"],
      "/api/news": NEWS_DATA,
      "/api/news/summary": NEWS_DATA,
      "/api/filings": NEWS_DATA,
      "/api/top": NEWS_DATA,
      "/api/news/ingest": NEWS_DATA,
    },
  },
};

export default nextConfig;
