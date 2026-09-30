// sync-data.mjs
// Copies the curated JSON + logo assets from the repo root (the Python/Streamlit
// project) into web/public so the Next.js app can serve them statically on Vercel.
// Runs automatically before `next dev` and `next build` (see package.json scripts).
//
// Why bundle some folders: the browser should fetch as few files as possible.
//   reports/*.json  -> public/data/reports.bundle.json  ({ node_name: report })
//   timelines/*.json-> public/data/timelines.bundle.json ([ {id, ...timeline} ])
//   chains/**/*.json-> public/data/chains/<stem>.json + chains/index.json (fetched on demand)
//   i18n/web/**     -> public/data/i18n/** (translation overlays for the language switch)
// Single files (merged_graph, company_metrics, ...) are copied as-is.

import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", ".."); // repo root (earnings-ai/)
const WEB = path.resolve(__dirname, ".."); // web/
const OUT_DATA = path.join(WEB, "public", "data");
const OUT_LOGOS = path.join(WEB, "public", "logos");

async function exists(p) {
  try { await fs.access(p); return true; } catch { return false; }
}

async function readJson(p) {
  return JSON.parse(await fs.readFile(p, "utf-8"));
}

async function ensureDir(p) {
  await fs.mkdir(p, { recursive: true });
}

// Recursively list files under a dir (returns absolute paths).
async function walk(dir) {
  const out = [];
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...(await walk(full)));
    else out.push(full);
  }
  return out;
}

async function copyFileIfExists(src, dst) {
  if (!(await exists(src))) { console.warn(`  (skip, missing) ${path.relative(ROOT, src)}`); return false; }
  await ensureDir(path.dirname(dst));
  await fs.copyFile(src, dst);
  return true;
}

async function main() {
  await ensureDir(OUT_DATA);
  await ensureDir(OUT_LOGOS);

  // 1) Single JSON files copied verbatim. Each entry lists candidate sources in
  //    priority order: the graph-DERIVED file under graph/ (written by derive.py via
  //    graph_build.py) wins over the hand-curated baseline at the repo root.
  const singles = [
    [["graph/merged_graph.json"], "merged_graph.json"],
    [["graph/company_metrics.json", "company_metrics.json"], "company_metrics.json"],
    [["company_metadata.json"], "company_metadata.json"],
    [["graph/capex_backlog.json", "capex_backlog.json"], "capex_backlog.json"],
    [["reports.json"], "reports_flat.json"],
    // Added 2026-09-05: derived views built by derive.py / evidence.py (skipped when absent).
    [["graph/exposure.json"], "exposure.json"],
    [["graph/evidence.json"], "evidence.json"],
    // Added 2026-09-11: per-pipeline enrichment status (enrich_status.py) for the Coverage tab.
    [["graph/enrich_status.json"], "enrich_status.json"],
    // Added 2026-09-27: Korean company names for the graph search box (graph_build.py).
    [["graph/company_ko.json"], "company_ko.json"],
  ];
  for (const [candidates, out] of singles) {
    let picked = null;
    for (const rel of candidates) {
      if (await exists(path.join(ROOT, rel))) { picked = rel; break; }
    }
    if (!picked) { console.warn(`  (skip, missing) ${candidates.join(" | ")}`); continue; }
    await copyFileIfExists(path.join(ROOT, picked), path.join(OUT_DATA, out));
    console.log(`  ✓ ${picked}`);
  }

  // 2) reports/*.json -> one bundle keyed by node_name (skip files starting with "_").
  const reportsDir = path.join(ROOT, "reports");
  const reportBundle = {};
  if (await exists(reportsDir)) {
    for (const f of await walk(reportsDir)) {
      const base = path.basename(f);
      if (!base.endsWith(".json") || base.startsWith("_")) continue;
      const rep = await readJson(f);
      const key = rep.node_name || path.basename(base, ".json");
      reportBundle[key] = rep;
    }
    await fs.writeFile(path.join(OUT_DATA, "reports.bundle.json"), JSON.stringify(reportBundle));
    console.log(`  ✓ reports.bundle.json (${Object.keys(reportBundle).length} reports)`);

    // Just the KEYS, as a tiny separate file. The graph only needs to know WHICH
    // companies have a report (to draw the badge) — it must not download the whole
    // bundle on first paint. The full bundle is lazy-loaded when a report is opened.
    const keys = Object.keys(reportBundle).sort();
    await fs.writeFile(path.join(OUT_DATA, "report_keys.json"), JSON.stringify(keys));
    console.log(`  ✓ report_keys.json (${keys.length} keys)`);
  }

  // 3) timelines -> one ordered array, each tagged with its filename stem as id.
  //    Preferred source: graph/timelines.bundle.json (curated tables + the graph-derived
  //    "Latest graph signals" table, written by derive.py). Fallback: bundle the
  //    hand-curated timelines/*.json directly, exactly as before.
  const derivedTimelines = path.join(ROOT, "graph", "timelines.bundle.json");
  const timelinesDir = path.join(ROOT, "timelines");
  const timelineBundle = [];
  if (await exists(derivedTimelines)) {
    await fs.copyFile(derivedTimelines, path.join(OUT_DATA, "timelines.bundle.json"));
    const n = (await readJson(derivedTimelines)).length;
    console.log(`  ✓ graph/timelines.bundle.json (${n} timelines, graph-derived)`);
  } else if (await exists(timelinesDir)) {
    for (const f of await walk(timelinesDir)) {
      const base = path.basename(f);
      if (!base.endsWith(".json")) continue;
      const tl = await readJson(f);
      timelineBundle.push({ id: path.basename(base, ".json"), ...tl });
    }
    await fs.writeFile(path.join(OUT_DATA, "timelines.bundle.json"), JSON.stringify(timelineBundle));
    console.log(`  ✓ timelines.bundle.json (${timelineBundle.length} timelines)`);
  }

  // 4) chains/**/*.json -> flattened per-stem files + an index (fetched on demand by Chain 2D).
  const chainsDir = path.join(ROOT, "chains");
  const chainOut = path.join(OUT_DATA, "chains");
  const chainIndex = [];
  if (await exists(chainsDir)) {
    await ensureDir(chainOut);
    for (const f of await walk(chainsDir)) {
      const base = path.basename(f);
      if (!base.endsWith(".json")) continue;
      const stem = path.basename(base, ".json");
      const chain = await readJson(f);
      await fs.writeFile(path.join(chainOut, `${stem}.json`), JSON.stringify(chain));
      chainIndex.push({ id: stem, company: chain.company || stem, chain_focus: chain.chain_focus || "" });
    }
    chainIndex.sort((a, b) => a.id.localeCompare(b.id));
    await fs.writeFile(path.join(chainOut, "index.json"), JSON.stringify(chainIndex));
    console.log(`  ✓ chains/ (${chainIndex.length} chains)`);
  }

  // 5) quant (optional).
  await copyFileIfExists(path.join(ROOT, "quant", "results.json"), path.join(OUT_DATA, "quant", "results.json"));
  await copyFileIfExists(path.join(ROOT, "quant", "results_events.csv"), path.join(OUT_DATA, "quant", "results_events.csv"));

  // 6) logos: copy every file in static/logos (images + manifest.json) into public/logos.
  const logosDir = path.join(ROOT, "static", "logos");
  if (await exists(logosDir)) {
    let n = 0;
    for (const f of await walk(logosDir)) {
      const rel = path.relative(logosDir, f);
      await ensureDir(path.dirname(path.join(OUT_LOGOS, rel)));
      await fs.copyFile(f, path.join(OUT_LOGOS, rel));
      n++;
    }
    console.log(`  ✓ logos/ (${n} files)`);
  }

  // 7) i18n/web/** -> public/data/i18n/** (optional). The translation pipeline writes
  //    the overlays there: <lang>/<bundle>.json = { sha1(text)[0:12]: translated text }
  //    and company_names.json. Without it the site simply shows English everywhere.
  const i18nDir = path.join(ROOT, "i18n", "web");
  if (await exists(i18nDir)) {
    const out = path.join(OUT_DATA, "i18n");
    let n = 0;
    for (const f of await walk(i18nDir)) {
      const rel = path.relative(i18nDir, f);
      await ensureDir(path.dirname(path.join(out, rel)));
      await fs.copyFile(f, path.join(out, rel));
      n++;
    }
    console.log(`  ✓ i18n/ (${n} files)`);
  }

  console.log("Data sync complete.");
}

main().catch((e) => { console.error(e); process.exit(1); });
