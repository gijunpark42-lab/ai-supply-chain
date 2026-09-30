"use client";

// i18n.tsx — the site's language switch (EN / 한국어 / 中文 / 日本語).
//
// Three kinds of text get translated, each by its own function:
//   t("English UI text")   → the hard-coded interface strings, looked up in
//                            lib/ui-strings.ts by their English wording.
//   tr(englishDataText)    → text that comes from the data files (products,
//                            signals, figures, timeline cells…). Translations live
//                            in overlay files /data/i18n/<lang>/<bundle>.json =
//                            { sha1(text)[0:12]: translatedText } and are loaded
//                            lazily, one bundle at a time.
//   name(companyId)        → a company's local name from /data/i18n/company_names.json.
// Anything without a translation falls back to the English original, so a
// missing overlay never breaks the page.
//
// IMPORTANT: English strings are still the LOGIC KEYS everywhere (node ids,
// source labels, evidence keys…). Translate only at the moment text is shown.
//
// The functions are plain module-level functions reading a module-level `cur`
// language, so non-React helpers (lib/chain2d.ts innerHTML, lib/table.ts labels)
// can call them too. Components call useLang() so they RE-RENDER when the
// language changes or an overlay bundle finishes loading.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { UI } from "./ui-strings";

export type Lang = "en" | "ko" | "zh" | "ja";
export const LANGS: { code: Lang; label: string }[] = [
  { code: "en", label: "EN" },
  { code: "ko", label: "한국어" },
  { code: "zh", label: "中文" },
  { code: "ja", label: "日本語" },
];
// HTML lang attribute per language (zh = Simplified Chinese).
const HTML_LANG: Record<Lang, string> = { en: "en", ko: "ko", zh: "zh-Hans", ja: "ja" };
const STORAGE_KEY = "ui.lang";

export type Bundle = "graph" | "metrics" | "timelines" | "capex" | "exposure" | "reports" | "reportkeys";

// ── Module state ───────────────────────────────────────────────────────────
let cur: Lang = "en";
// Loaded overlay text per language: hash → translated text (all bundles merged;
// a hash identifies one English string, so bundles never disagree).
const overlay: Record<Lang, Map<string, string>> = { en: new Map(), ko: new Map(), zh: new Map(), ja: new Map() };
// "ko/graph" → the load promise (so each bundle is fetched once).
const loading = new Map<string, Promise<void>>();
let companyNames: Record<string, Partial<Record<Lang, string>>> = {};
let namesLoad: Promise<void> | null = null;
// Called after anything finishes loading, so the provider can re-render the app.
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((fn) => fn());

export function currentLang(): Lang {
  return cur;
}

// ── SHA-1 (synchronous, small) ─────────────────────────────────────────────
// Must match Python's hashlib.sha1(text.encode("utf-8")).hexdigest()[:12] exactly,
// on the UNTRIMMED string. Results are memoised: the same strings are hashed on
// every render.
const hashCache = new Map<string, string>();
const encoder = typeof TextEncoder !== "undefined" ? new TextEncoder() : null;

function sha1Hex(bytes: Uint8Array): string {
  const len = bytes.length;
  // Pad: 0x80, zeros, then the 64-bit bit length (big endian) → multiple of 64 bytes.
  const total = (((len + 8) >> 6) + 1) << 6;
  const buf = new Uint8Array(total);
  buf.set(bytes);
  buf[len] = 0x80;
  const view = new DataView(buf.buffer);
  view.setUint32(total - 4, (len * 8) >>> 0);
  view.setUint32(total - 8, Math.floor((len * 8) / 0x100000000));
  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
  const w = new Uint32Array(80);
  for (let off = 0; off < total; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4);
    for (let i = 16; i < 80; i++) {
      const x = w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16];
      w[i] = (x << 1) | (x >>> 31);
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let i = 0; i < 80; i++) {
      let f: number, k: number;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const tmp = (((a << 5) | (a >>> 27)) + f + e + k + w[i]) >>> 0;
      e = d; d = c; c = (b << 30) | (b >>> 2); b = a; a = tmp;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
  }
  return [h0, h1, h2, h3, h4].map((v) => (v >>> 0).toString(16).padStart(8, "0")).join("");
}

/** sha1(utf8(text)).hex[0:12] — the overlay key of a data string. */
export function textHash(text: string): string {
  let h = hashCache.get(text);
  if (h === undefined) {
    const bytes = encoder ? encoder.encode(text) : new Uint8Array(0);
    h = sha1Hex(bytes).slice(0, 12);
    hashCache.set(text, h);
  }
  return h;
}

// ── Translators ───────────────────────────────────────────────────────────

/**
 * UI string: English literal → current language (English when missing).
 * `{name}` placeholders are filled from `vars` AFTER the lookup, so the
 * dictionary key is the template ("{n} companies"), not the filled text.
 */
export function t(en: string, vars?: Record<string, string | number>): string {
  let s = en;
  if (cur !== "en") {
    const row = UI[en];
    if (row) s = row[cur === "ko" ? 0 : cur === "zh" ? 1 : 2] || en;
  }
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  return s;
}

/** Data text: English → overlay translation for the current language (English when missing). */
export function tr(en: string | null | undefined): string {
  if (!en) return en ?? "";
  if (cur === "en") return en;
  const map = overlay[cur];
  if (map.size === 0) return en;
  return map.get(textHash(en)) ?? en;
}

/** tr() for a " · "-joined list (productIn() joins several products that way;
 *  each part is its own overlay entry). */
export function trJoined(s: string | null | undefined): string {
  return s ? s.split(" · ").map(tr).join(" · ") : "";
}

/** A timeline date label (lib/signals.ts DATE_RE match) in the current language:
 *  "late 2026" → "2026년 말" / "2026年底" / "2026年末"; "by fiscal 2027" → "FY2027까지" …
 *  Quarter / half forms (Q2 FY2026, 1H 2026, H2 2026) and bare years stay as written. */
const WHEN_WORDS: Record<Exclude<Lang, "en">, Record<string, (y: string, fy: boolean) => string>> = {
  ko: {
    early: (y, fy) => `${y}${fy ? "" : "년"} 초`,
    mid: (y, fy) => `${y}${fy ? "" : "년"} 중반`,
    late: (y, fy) => `${y}${fy ? "" : "년"} 말`,
    "end of": (y, fy) => `${y}${fy ? "" : "년"} 말`,
    exiting: (y, fy) => `${y}${fy ? "" : "년"} 말`,
    through: (y, fy) => `${y}${fy ? "" : "년"}까지`,
    by: (y, fy) => `${y}${fy ? "" : "년"}까지`,
  },
  zh: {
    early: (y, fy) => `${y}${fy ? "" : "年"}初`,
    mid: (y, fy) => `${y}${fy ? "" : "年"}中`,
    late: (y, fy) => `${y}${fy ? "" : "年"}底`,
    "end of": (y, fy) => `${y}${fy ? "" : "年"}底`,
    exiting: (y, fy) => `${y}${fy ? "" : "年"}底`,
    through: (y, fy) => `至${y}${fy ? "" : "年"}`,
    by: (y, fy) => `${y}${fy ? "" : "年"}前`,
  },
  ja: {
    early: (y, fy) => `${y}${fy ? "" : "年"}初め`,
    mid: (y, fy) => `${y}${fy ? "" : "年"}半ば`,
    late: (y, fy) => `${y}${fy ? "" : "年"}後半`,
    "end of": (y, fy) => `${y}${fy ? "" : "年"}末`,
    exiting: (y, fy) => `${y}${fy ? "" : "年"}末`,
    through: (y, fy) => `${y}${fy ? "" : "年"}まで`,
    by: (y, fy) => `${y}${fy ? "" : "年"}までに`,
  },
};
const WHEN_RE = /^(early|mid|late|end of|exiting|through|by)\s*(calendar |CY|fiscal |FY)?\s*(20\d\d)$/i;

export function trWhen(when: string): string {
  if (cur === "en" || !when) return when;
  const m = WHEN_RE.exec(when.trim());
  if (!m) return when; // Q2 2026, 1H 2026, FY2026, 2026 … are fine as written
  const word = m[1].toLowerCase();
  const fiscal = !!m[2] && /^(fiscal|FY)/i.test(m[2]);
  const year = fiscal ? `FY${m[3]}` : m[3];
  const fmt = WHEN_WORDS[cur][word];
  return fmt ? fmt(year, fiscal) : when;
}

/** A company's display name: its local name for the current language, else the id. */
export function name(id: string): string {
  if (cur === "en" || !id) return id;
  return companyNames[id]?.[cur] || id;
}

/** Every localised name of a company (all languages) — for the search index. */
export function localNames(id: string): string[] {
  const row = companyNames[id];
  return row ? (Object.values(row).filter(Boolean) as string[]) : [];
}

// ── Loading ───────────────────────────────────────────────────────────────

function loadBundle(lang: Lang, bundle: Bundle): Promise<void> {
  if (lang === "en") return Promise.resolve();
  const key = `${lang}/${bundle}`;
  let p = loading.get(key);
  if (!p) {
    p = fetch(`/data/i18n/${lang}/${bundle}.json`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((obj: Record<string, string>) => {
        const map = overlay[lang];
        for (const k in obj) if (typeof obj[k] === "string" && obj[k]) map.set(k, obj[k]);
        notify();
      })
      .catch(() => {}); // no overlay yet → English
    loading.set(key, p);
  }
  return p;
}

function loadNames(): Promise<void> {
  if (!namesLoad) {
    namesLoad = fetch("/data/i18n/company_names.json")
      .then((r) => (r.ok ? r.json() : {}))
      .then((obj: Record<string, Partial<Record<Lang, string>>>) => {
        companyNames = obj && typeof obj === "object" ? obj : {};
        notify();
      })
      .catch(() => {});
  }
  return namesLoad;
}

// ── React side ────────────────────────────────────────────────────────────

interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  /** Changes whenever the language changes or more translations arrive —
   *  put it in useMemo deps that call tr()/name(). */
  rev: string;
}
const LangContext = createContext<Ctx>({ lang: "en", setLang: () => {}, rev: "en:0" });

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  const [n, setN] = useState(0);
  // Keep the module-level language in step BEFORE the children render.
  cur = lang;

  // First visit = English; later visits = what the viewer picked last.
  useEffect(() => {
    try {
      const s = window.localStorage.getItem(STORAGE_KEY) as Lang | null;
      if (s && s in HTML_LANG) setLangState(s);
    } catch {}
    const bump = () => setN((x) => x + 1);
    listeners.add(bump);
    loadNames();
    return () => {
      listeners.delete(bump);
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = HTML_LANG[lang];
    // The graph bundle is needed everywhere (panel, tooltips, lists).
    loadBundle(lang, "graph");
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {}
  }, []);

  const value = useMemo(() => ({ lang, setLang, rev: `${lang}:${n}` }), [lang, setLang, n]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

/**
 * Subscribe a component to the language. `bundles` = the data overlays this
 * component displays; they are fetched on mount (non-English only).
 */
export function useLang(bundles?: Bundle[]) {
  const ctx = useContext(LangContext);
  const key = bundles ? bundles.join(",") : "";
  useEffect(() => {
    if (!key || ctx.lang === "en") return;
    for (const b of key.split(",")) loadBundle(ctx.lang, b as Bundle);
  }, [key, ctx.lang]);
  return { lang: ctx.lang, setLang: ctx.setLang, rev: ctx.rev, t, tr, name };
}

/** The EN | 한국어 | 中文 | 日本語 segmented control. */
export function LangSwitch({ className = "" }: { className?: string }) {
  const { lang, setLang } = useLang();
  return (
    <div className={"lang-switch " + className} role="group" aria-label={t("Language")}>
      {LANGS.map((l) => (
        <button
          key={l.code}
          type="button"
          lang={HTML_LANG[l.code]}
          className={"lang-btn" + (lang === l.code ? " on" : "")}
          aria-pressed={lang === l.code}
          onClick={() => setLang(l.code)}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}
