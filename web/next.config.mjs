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
      // The remote MCP server (lib/mapMcp.ts) answers from the graph, the screener, the Korean names and the
      // evidence excerpts (user, 2026-10-20: the enriched map from the phone).
      "/api/mcp": [
        "./public/data/merged_graph.json",
        "./public/data/company_metrics.json",
        "./public/data/company_ko.json",
        "./public/data/evidence.json",
      ],
    },
  },
  // Browser cache for logo images: a returning visitor reuses them for 7 days
  // instead of asking the server again. A logo replaced under the same file name
  // can show the old version for up to 7 days.
  // manifest.json (the list of logos, which changes as companies are added) is
  // NOT cached; the later rule wins for the same header key.
  async headers() {
    return [
      {
        source: "/logos/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=604800" }],
      },
      {
        source: "/logos/manifest.json",
        headers: [{ key: "Cache-Control", value: "public, max-age=0, must-revalidate" }],
      },
    ];
  },
};

export default nextConfig;
