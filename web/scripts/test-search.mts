// Tests for src/lib/search.ts — the graph SearchBox's matching and ranking.
//
// Run from web/ (Node 22.18+ runs TypeScript files directly; --no-warnings hides its
// "module type" notice about src/lib/search.ts):
//     node --no-warnings scripts/test-search.mts
//
// The first group uses tiny made-up companies, so it never depends on the data.
// The second reads the real public/data files and skips itself when they are missing.

import assert from "node:assert/strict";
import fs from "node:fs";
import { buildSearchIndex, koreanTerms, normalize, searchNodes } from "../src/lib/search.ts";

let failed = 0;
function test(name: string, fn: () => void) {
  try {
    fn();
    console.log("ok   " + name);
  } catch (e) {
    failed++;
    console.log("FAIL " + name + "\n     " + (e as Error).message.split("\n").join("\n     "));
  }
}

// A made-up company with only the fields search.ts reads.
function company(id: string, degree: number, products: [string, string?][], extra: Record<string, unknown> = {}) {
  return {
    id,
    degree,
    ticker: null,
    sectors: [],
    layers: [],
    domains: [],
    products: products.map(([product, sub_sector]) => ({ chain: "test", product, sub_sector: sub_sector ?? null })),
    ...extra,
  } as any;
}

const NODES = [
  company("SK Hynix", 90, [["HBM4 stacks"]], { ticker: "000660.KS", layers: ["memory"] }),
  company("Samsung", 80, [["HBM3E stacks"]], { ticker: "005930.KS" }),
  company("Samsung Electro-Mechanics", 40, [["FC-BGA substrate"], ["MLCC"]]),
  company("Wolfspeed", 30, [["SiC wafers"]]),
  company("Broadcom", 95, [["custom ASIC design"]]),
  company("Ibiden", 35, [["ABF substrate"]], { sectors: ["FC-BGA Substrate"] }),
  company("Intel", 99, [["server CPUs; package substrate buyer"]]),
  company("Corning", 20, [["glass substrate cores"]]),
  company("Coherent", 50, [["800G transceivers", "Co-Packaged Optics (CPO)"]]),
];
const KO = {
  "SK Hynix": ["SK하이닉스", "하이닉스"],
  Samsung: ["삼성전자"],
  "Samsung Electro-Mechanics": ["삼성전기"],
};
const INDEX = buildSearchIndex(NODES, KO);
const ids = (q: string) => searchNodes(INDEX, q, 50).hits.map((h) => h.node.id);

test("normalize keeps Korean syllables and strips accents", () => {
  assert.equal(normalize("SK하이닉스"), "sk하이닉스");
  assert.equal(normalize("Résonac (Showa Denko)"), "resonac showa denko");
});

test("a component matches word starts only: sic finds SiC wafers, not ASIC", () => {
  assert.deepEqual(ids("sic"), ["Wolfspeed"]);
});

test("every maker of a component joins the group, beyond the row limit", () => {
  const r = searchNodes(INDEX, "hbm", 1);
  assert.equal(r.hits.length, 1);
  assert.equal(r.hits[0].node.id, "SK Hynix"); // better connected first
  assert.deepEqual(r.group?.ids.sort(), ["SK Hynix", "Samsung"]);
  assert.equal(r.group?.label, "hbm");
  assert.equal(r.hits[0].why, "HBM4 stacks");
});

test("a company filed under the component ranks before one that only mentions it", () => {
  // Intel is better connected, but only BUYS substrates; Ibiden's sector is FC-BGA Substrate.
  assert.deepEqual(ids("substrate").slice(0, 2), ["Ibiden", "Intel"]);
});

test("sub-sectors and layer names are searchable", () => {
  assert.deepEqual(ids("cpo"), ["Coherent"]);
  assert.ok(ids("memory").includes("SK Hynix"));
});

test("a company-name match still ranks first", () => {
  assert.deepEqual(ids("samsung").slice(0, 2), ["Samsung", "Samsung Electro-Mechanics"]);
});

test("no group for one company or one letter", () => {
  assert.equal(searchNodes(INDEX, "sic").group, null); // only Wolfspeed
  assert.equal(searchNodes(INDEX, "a").group, null);
});

test("Korean company names: starts-with and contains", () => {
  const r = searchNodes(INDEX, "삼성", 10);
  assert.deepEqual(r.hits.map((h) => h.node.id), ["Samsung", "Samsung Electro-Mechanics"]);
  assert.equal(r.hits[0].kind, "ko");
  const h = searchNodes(INDEX, "하이닉스", 10).hits;
  assert.equal(h[0].node.id, "SK Hynix");
  assert.equal(h[0].why, "SK하이닉스");
  assert.equal(searchNodes(INDEX, "sk 하이닉스").hits[0].node.id, "SK Hynix"); // spaces ignored
});

test("Korean component words search their English words", () => {
  assert.deepEqual(koreanTerms("기판"), ["substrate", "pcb"]);
  const r = searchNodes(INDEX, "기판", 10);
  assert.deepEqual(r.group?.terms, ["substrate", "pcb"]);
  assert.deepEqual(r.group?.ids.sort(), ["Corning", "Ibiden", "Intel", "Samsung Electro-Mechanics"]);
  assert.ok(koreanTerms("유리").includes("glass substrate")); // still typing 유리기판
  assert.deepEqual(koreanTerms("기판회사"), ["substrate", "pcb"]); // contains 기판
  assert.deepEqual(koreanTerms("기"), []); // one syllable that is not a word
});

// ── Real data (skipped when the files are missing) ─────────────────────────
const GRAPH = "public/data/merged_graph.json";
if (fs.existsSync(GRAPH)) {
  const graph = JSON.parse(fs.readFileSync(GRAPH, "utf8"));
  const degree: Record<string, number> = {};
  for (const e of graph.edges) {
    degree[e.source] = (degree[e.source] || 0) + 1;
    degree[e.target] = (degree[e.target] || 0) + 1;
  }
  const nodes = graph.nodes.map((n: any) => ({ ...n, degree: degree[n.id] || 0 }));
  const koFile = "public/data/company_ko.json";
  const ko = fs.existsSync(koFile) ? JSON.parse(fs.readFileSync(koFile, "utf8")) : {};
  const index = buildSearchIndex(nodes, ko);

  test("real data: HBM has 20+ makers and every hit is in the group", () => {
    const r = searchNodes(index, "hbm", 500);
    assert.ok((r.group?.ids.length || 0) >= 20, "group size " + r.group?.ids.length);
    for (const h of r.hits.filter((x) => x.kind === "product")) assert.ok(r.group!.ids.includes(h.node.id));
  });

  test("real data: sic never matches through ASIC alone", () => {
    for (const h of searchNodes(index, "sic", 500).hits) {
      assert.ok(!/asic/i.test(h.why || "") || /\bsic\b/i.test(h.why || ""), h.node.id + ": " + h.why);
    }
  });

  if (Object.keys(ko).length) {
    test("real data: Korean names find the big Korean companies", () => {
      assert.equal(searchNodes(index, "삼성전자").hits[0]?.node.id, "Samsung");
      assert.equal(searchNodes(index, "하이닉스").hits[0]?.node.id, "SK Hynix");
      assert.equal(searchNodes(index, "한미반도체").hits[0]?.node.id, "Hanmi Semiconductor");
    });
    test("real data: every Korean component word finds at least one company", () => {
      const none = ["기판", "메모리", "웨이퍼", "광모듈", "냉각", "전력", "변압기", "패키징", "장비", "소재"]
        .filter((w) => !searchNodes(index, w).group);
      assert.deepEqual(none, []);
    });
  }
} else {
  console.log("skip real-data tests (no " + GRAPH + ")");
}

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
