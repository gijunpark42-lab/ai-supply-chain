// /api/news — the last 24 hours of headlines for the /news terminal (lib/news.ts).
// Display only: it reads feeds and the graph, writes nothing.
//
// The CDN keeps a copy for 3 minutes, so a page polling every minute costs the
// sources (and Gemini's free tier, which translates the new non-English headlines)
// one refresh per region every 3 minutes. Past that it still serves the old copy
// at once while refreshing behind it: a cold rebuild translates ~700 headlines
// and takes ~25 s, which no one should have to wait for.

import { NextResponse } from "next/server";
import { getNewsFeed } from "@/lib/news";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const feed = await getNewsFeed();
  return NextResponse.json(feed, {
    headers: { "Cache-Control": "public, s-maxage=180, stale-while-revalidate=86400" },
  });
}
