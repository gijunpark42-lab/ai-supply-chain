/** @type {import('next').NextConfig} */
const nextConfig = {
  // Strict mode double-mounts components in dev, which tears down and rebuilds
  // the WebGL context and can blank the force graph. Off for a stable canvas.
  reactStrictMode: false,
  // react-force-graph pulls in three.js; nothing special needed, but keep
  // transpilePackages ready in case a nested ESM dep needs it.
  eslint: { ignoreDuringBuilds: true },
  experimental: {
    // /api/ask reads the graph from disk for its lookups (lib/askAgent.ts);
    // ship the file with that function on Vercel.
    outputFileTracingIncludes: { "/api/ask": ["./public/data/merged_graph.json"] },
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
