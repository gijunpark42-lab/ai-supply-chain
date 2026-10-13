// /api/news — the last 24 hours of headlines for the /news terminal (lib/news.ts).
// Display only: it reads feeds and the graph, writes nothing.
//
// The CDN keeps a copy for 2 minutes (and serves the old one while it refreshes),
// so a page polling every minute costs the news sources one fetch per region.

import { NextResponse } from "next/server";
import { getNewsFeed } from "@/lib/news";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const feed = await getNewsFeed();
  return NextResponse.json(feed, {
    headers: { "Cache-Control": "public, s-maxage=120, stale-while-revalidate=600" },
  });
}
