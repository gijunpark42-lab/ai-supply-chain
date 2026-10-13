// /api/top — the day's important Reuters / FT stories, rated by Gemini in the
// ingest job, for the /news terminal's Top News tab (lib/top.ts). Display only:
// writes nothing.
//
// Cached like /api/news: 3 minutes at the CDN, then the old copy is served at once
// while a fresh one is built behind it.

import { NextResponse } from "next/server";
import { cdnCache } from "@/lib/news";
import { getTopFeed } from "@/lib/top";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const feed = await getTopFeed();
  return NextResponse.json(feed, {
    headers: cdnCache(180, 86400),
  });
}
