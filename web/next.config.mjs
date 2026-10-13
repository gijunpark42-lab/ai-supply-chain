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
    // /api/ask reads the graph from disk for its lookups (lib/askAgent.ts), and
    // /api/news* read it + the local-name files to tag headlines (lib/news.ts);
    // ship the files with those functions on Vercel.
    outputFileTracingIncludes: {
      "/api/ask": ["./public/data/merged_graph.json"],
      "/api/news": NEWS_DATA,
      "/api/news/summary": NEWS_DATA,
    },
  },
};

export default nextConfig;
