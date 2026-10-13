// /api/news — the last 24 hours of headlines for the /news terminal (lib/news.ts).
// Display only: it reads feeds and the graph, writes nothing.
//
// The CDN keeps a copy for 3 minutes, so a page polling every minute costs the
// sources one refresh per region every 3 minutes. Past that it still serves the
// old copy at once while refreshing behind it, so no one waits for a rebuild.

import { NextResponse } from "next/server";
import { withDigests } from "@/lib/digests";
import { cdnCache, getNewsFeed } from "@/lib/news";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  // Items carry the summaries the ingest job wrote ahead of time (lib/digests.ts).
  const feed = await withDigests(await getNewsFeed());
  return NextResponse.json(feed, {
    headers: cdnCache(180, 86400),
  });
}
