// /api/top — the day's important Reuters / FT stories, rated by Gemini, for the
// /news terminal's Top News tab (lib/top.ts). Display only: writes nothing.
//
// Cached like /api/news: 3 minutes at the CDN, then the old copy is served at once
// while a fresh one (rating only the new stories) is built behind it.

import { NextResponse } from "next/server";
import { getTopFeed } from "@/lib/top";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const feed = await getTopFeed();
  return NextResponse.json(feed, {
    headers: { "Cache-Control": "public, s-maxage=180, stale-while-revalidate=86400" },
  });
}
