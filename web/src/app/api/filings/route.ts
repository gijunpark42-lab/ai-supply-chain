// /api/filings — the last day of DART / EDINET / SEC filings by map companies, for
// the /news terminal's Filings tab (lib/filings.ts). Display only: writes nothing.
//
// The CDN keeps a copy for 10 minutes: filings arrive slower than news, and DART's
// daily call allowance is shared with the nightly enrich. Past that it serves the
// old copy at once while refreshing behind it.

import { NextResponse } from "next/server";
import { getFilingsFeed } from "@/lib/filings";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const feed = await getFilingsFeed();
  return NextResponse.json(feed, {
    headers: { "Cache-Control": "public, s-maxage=600, stale-while-revalidate=86400" },
  });
}
