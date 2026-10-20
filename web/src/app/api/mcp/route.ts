// /api/mcp — the enriched supply-chain map as a remote, read-only MCP server (user, 2026-10-20: use it from the phone,
// and have it follow every enrich). Add the URL as a custom connector in Claude (Settings → Connectors) and it works
// in the Claude apps on phone, web and desktop. The lookups live in lib/mapMcp.ts; this file only declares the tools.
// It serves the same public data the website shows (public/data, redeployed by every nightly publish), so it needs no
// sign-in, and it never writes anything.

import { createMcpHandler } from "mcp-handler";
import { z } from "zod";
import {
  chainOverview, companyEntries, companyProfile, mapStatus, relationship, searchCompanies, searchEntries,
  sourceExcerpt, supplyChain,
} from "@/lib/mapMcp";

// Every tool answers with one JSON text block.
const json = (value: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(value) }] });
const readOnly = { readOnlyHint: true, openWorldHint: false };

const handler = createMcpHandler(
  (server) => {
    server.registerTool("search_companies", {
      title: "Search companies",
      description: "Find companies on the map by name, ticker, Korean name, sector or product words (e.g. 'HBM', 'CoWoS', '하이닉스', 'transformer').",
      inputSchema: z.object({ query: z.string(), limit: z.number().int().min(1).max(50).default(20) }),
      annotations: readOnly,
    }, async ({ query, limit }) => json(searchCompanies(query, limit)));

    server.registerTool("company_profile", {
      title: "Company profile",
      description: "Everything the map holds on one company: where it sits in each chain (product), its AI-chain suppliers and customers with the latest deal on each, its non-AI relationships, screener metrics and its newest facts with source labels.",
      inputSchema: z.object({ company: z.string(), entries: z.number().int().min(1).max(100).default(25) }),
      annotations: readOnly,
    }, async ({ company, entries }) => json(companyProfile(company, entries)));

    server.registerTool("company_entries", {
      title: "Company facts",
      description: "All facts on one company (its entries and the deals on its edges), optionally filtered by words (query) and date (since, YYYY-MM-DD). Newest first.",
      inputSchema: z.object({
        company: z.string(), query: z.string().default(""), since: z.string().default(""),
        limit: z.number().int().min(1).max(200).default(50),
      }),
      annotations: readOnly,
    }, async ({ company, query, since, limit }) => json(companyEntries(company, query, since, limit)));

    server.registerTool("search_entries", {
      title: "Search facts",
      description: "Search every fact on the map for all the words in query (e.g. 'HBM4 qualification', 'gigawatt'). Optional: company, chain file name (e.g. 'hbm_memory'), since (YYYY-MM-DD). Newest first.",
      inputSchema: z.object({
        query: z.string(), company: z.string().default(""), chain: z.string().default(""),
        since: z.string().default(""), limit: z.number().int().min(1).max(200).default(40),
      }),
      annotations: readOnly,
    }, async ({ query, company, chain, since, limit }) => json(searchEntries(query, company, chain, since, limit)));

    server.registerTool("relationship", {
      title: "Relationship between two companies",
      description: "Every recorded tie between two companies, both directions: AI-chain edges with all their deals, and non-AI relationships with their quotes.",
      inputSchema: z.object({ company_a: z.string(), company_b: z.string() }),
      annotations: readOnly,
    }, async ({ company_a, company_b }) => json(relationship(company_a, company_b)));

    server.registerTool("supply_chain", {
      title: "Supply chain",
      description: "Who supplies the company (up), whom it supplies (down) or both, through AI-chain edges, 1 or 2 steps away.",
      inputSchema: z.object({
        company: z.string(), direction: z.enum(["up", "down", "both"]).default("both"),
        depth: z.number().int().min(1).max(2).default(1),
      }),
      annotations: readOnly,
    }, async ({ company, direction, depth }) => json(supplyChain(company, direction, depth)));

    server.registerTool("chain_overview", {
      title: "Chain overview",
      description: "Without chain: every product chain with its company and edge counts. With a chain file name (e.g. 'nvidia_vera_rubin', 'hbm_memory'): its companies by layer / sector with products, and its edges.",
      inputSchema: z.object({ chain: z.string().default("") }),
      annotations: readOnly,
    }, async ({ chain }) => json(chainOverview(chain)));

    server.registerTool("source_excerpt", {
      title: "Source excerpt",
      description: "The verbatim passage of the company document behind a fact: the company, the entry's source label, optionally words of its signal. News-interview entries have no excerpt by design.",
      inputSchema: z.object({ company: z.string(), source_label: z.string(), contains: z.string().default("") }),
      annotations: readOnly,
    }, async ({ company, source_label, contains }) => json(sourceExcerpt(company, source_label, contains)));

    server.registerTool("map_status", {
      title: "Map status",
      description: "How big and how fresh the map is: companies, edges, facts, newest source date.",
      inputSchema: z.object({}),
      annotations: readOnly,
    }, async () => json(mapStatus()));
  },
  {
    serverInfo: { name: "nodus42", version: "1.0.0" },
    instructions:
      "Nodus42: a supply-chain map of AI and adjacent companies built ONLY from company documents (earnings calls, " +
      "SEC / DART / TDnet / EDINET / MOPS / cninfo filings, company IR releases, investor-conference talks, executives' " +
      "own words in news interviews). Analyst opinion and news articles are never in it. Start with search_companies or " +
      "company_profile; use search_entries for a topic; relationship / supply_chain for who supplies whom; source_excerpt " +
      "for the verbatim passage. Cite the source label of every fact you use. Say so when the map has nothing on a question.",
  },
);

export { handler as GET, handler as POST, handler as DELETE };
