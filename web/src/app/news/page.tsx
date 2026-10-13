"use client";

// /news — a 24-hour news terminal beside the main site, opened in its own window
// from the header (like /tower). Headlines from Polygon, Finnhub and Google News
// (lib/news.ts), newest first, refreshed every minute; click one for its summary
// and the companies / tickers it names (lib/newsSummary.ts).
// Display only: news never feeds the graph or enrich.

import { useEffect, useMemo, useRef, useState } from "react";
import { LangProvider, LangSwitch, useLang } from "@/lib/i18n";
import type { NewsFeed, NewsItem } from "@/lib/news";
import type { NewsSummary } from "@/lib/newsSummary";
import "./news.css";

const POLL_MS = 60_000;
const CHIPS_SHOWN = 3; // per row; the rest is "+N"
const FEED_LABEL: Record<NewsItem["feed"], string> = {
  polygon: "Polygon",
  finnhub: "Finnhub",
  google: "Google News",
};

const hhmm = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });

export default function NewsPage() {
  return (
    <LangProvider>
      <NewsTerminal />
    </LangProvider>
  );
}

function NewsTerminal() {
  const { t, name, lang, rev } = useLang();
  const [feed, setFeed] = useState<NewsFeed | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set()); // ids that arrived on the last refresh
  const [sel, setSel] = useState<NewsItem | null>(null);
  const [mapOnly, setMapOnly] = useState(false);
  const [query, setQuery] = useState("");
  const seen = useRef<Set<string> | null>(null);

  useEffect(() => {
    document.title = `${t("News")} — ${t("AI Supply Chain")}`;
  }, [t, lang]);

  useEffect(() => {
    let alive = true;
    const load = () => {
      if (document.hidden) return;
      fetch("/api/news")
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((f: NewsFeed) => {
          if (!alive) return;
          const prev = seen.current;
          if (prev) setFresh(new Set(f.items.filter((i) => !prev.has(i.id)).map((i) => i.id)));
          seen.current = new Set(f.items.map((i) => i.id));
          setFeed(f);
          setErr(null);
        })
        .catch((e) => alive && setErr(String(e?.message || e)));
    };
    load();
    const timer = setInterval(load, POLL_MS);
    document.addEventListener("visibilitychange", load);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
    };
  }, []);

  const items = useMemo(() => {
    if (!feed) return [];
    const q = query.trim().toLowerCase();
    return feed.items.filter((it) => {
      if (mapOnly && !it.companies.length) return false;
      if (!q) return true;
      return (
        it.title.toLowerCase().includes(q) ||
        it.source.toLowerCase().includes(q) ||
        it.tickers.some((x) => x.toLowerCase().includes(q)) ||
        it.companies.some(
          (id) =>
            id.toLowerCase().includes(q) ||
            name(id).toLowerCase().includes(q) ||
            (feed.tickers[id] || "").toLowerCase().includes(q)
        )
      );
    });
    // `rev` changes when company names finish loading (name()).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feed, mapOnly, query, rev]);

  return (
    <div className={"news-term" + (sel ? " has-sel" : "")}>
      <header className="news-head">
        <span className="news-brand">{t("News")}</span>
        <span className="news-sub">{t("Last 24 hours")}</span>
        <Clock />
        <span className="news-count">{feed ? t("{n} headlines", { n: items.length.toLocaleString() }) : ""}</span>
        <button
          type="button"
          className={"news-toggle" + (mapOnly ? " on" : "")}
          aria-pressed={mapOnly}
          onClick={() => setMapOnly((v) => !v)}
        >
          {t("Map companies only")}
        </button>
        <input
          className="news-filter"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("Filter by company, ticker or word")}
          aria-label={t("Filter by company, ticker or word")}
        />
        <LangSwitch />
      </header>

      <div className="news-body">
        <ol className="news-list" aria-label={t("News")}>
          {!feed && !err && <li className="news-note">{t("Loading headlines")}</li>}
          {err && !feed && <li className="news-note">{t("Could not load the news: {error}", { error: err })}</li>}
          {feed && !items.length && <li className="news-note">{t("No headlines match.")}</li>}
          {items.map((it) => (
            <li key={it.id}>
              <button
                type="button"
                className={"news-row" + (sel?.id === it.id ? " on" : "") + (fresh.has(it.id) ? " fresh" : "")}
                aria-pressed={sel?.id === it.id}
                onClick={() => setSel(it)}
              >
                <time className="news-time" dateTime={new Date(it.time).toISOString()}>
                  {hhmm(it.time)}
                </time>
                <span className="news-src">{it.source}</span>
                <span className="news-title">{it.title}</span>
                <Chips item={it} tickers={feed!.tickers} />
              </button>
            </li>
          ))}
        </ol>

        <section className="news-detail" aria-live="polite">
          {sel ? (
            <Detail key={sel.id} item={sel} tickers={feed?.tickers || {}} onBack={() => setSel(null)} />
          ) : (
            <p className="news-note">{t("Pick a headline to see its summary and related tickers.")}</p>
          )}
        </section>
      </div>

      <footer className="news-foot">
        {feed?.feeds.map((f) => (
          <span key={f.name} className={f.failed ? "bad" : ""}>
            {FEED_LABEL[f.name]} {f.count.toLocaleString()}
            {f.failed ? " !" : ""}
          </span>
        ))}
        {feed && <span>{t("Updated {time}", { time: hhmm(feed.at) })}</span>}
        {err && feed && <span className="bad">{err}</span>}
      </footer>
    </div>
  );
}

/** The clock ticks on its own so the list does not re-render every second. */
function Clock() {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="news-clock">
      {now ? new Date(now).toLocaleTimeString([], { hour12: false }) : ""}
    </span>
  );
}

function Chips({ item, tickers }: { item: NewsItem; tickers: Record<string, string | null> }) {
  const { name } = useLang();
  const labels = [
    ...item.companies.map((id) => ({ text: tickers[id] || name(id), map: true })),
    ...item.tickers.map((x) => ({ text: x, map: false })),
  ];
  if (!labels.length) return <span className="news-chips" />;
  return (
    <span className="news-chips">
      {labels.slice(0, CHIPS_SHOWN).map((l, i) => (
        <span key={i} className={"news-chip" + (l.map ? " map" : "")}>
          {l.text}
        </span>
      ))}
      {labels.length > CHIPS_SHOWN && <span className="news-more">+{labels.length - CHIPS_SHOWN}</span>}
    </span>
  );
}

const KIND_LABEL: Record<NewsSummary["kind"], string> = {
  ai: "AI summary (Gemini)",
  lead: "Article opening (no AI summary)",
  feed: "Source summary",
  none: "No summary available — open the article.",
};

function Detail({
  item,
  tickers,
  onBack,
}: {
  item: NewsItem;
  tickers: Record<string, string | null>;
  onBack: () => void;
}) {
  const { t, name, lang } = useLang();
  const [res, setRes] = useState<NewsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setRes(null);
    setLoading(true);
    const qs = new URLSearchParams({ u: item.url, t: item.title, s: item.summary.slice(0, 1500), lang });
    fetch(`/api/news/summary?${qs}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: NewsSummary | null) => alive && setRes(j))
      .catch(() => {})
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [item.url, item.title, item.summary, lang]);

  const companies = [...new Set([...item.companies, ...(res?.companies || [])])];
  const ticker = { ...tickers, ...(res?.tickers || {}) };
  const others = [...new Set([...item.tickers, ...(res?.others || [])])];
  const lines = (res?.summary || "").split("\n").map((l) => l.trim()).filter(Boolean);
  const bullets = lines.length > 0 && lines.every((l) => /^[-*•]\s/.test(l));

  return (
    <article className="news-art">
      <button type="button" className="news-back" onClick={onBack}>
        ← {t("Back")}
      </button>
      <h2 className="news-art-title">{item.title}</h2>
      <p className="news-art-meta">
        <span>{item.source}</span>
        <span>{new Date(item.time).toLocaleString([], { hour12: false })}</span>
        <span>{FEED_LABEL[item.feed]}</span>
      </p>
      <a className="news-open" href={res?.url || item.url} target="_blank" rel="noopener noreferrer">
        {t("Open article")} ↗
      </a>

      <div className="news-sum">
        {loading ? (
          <p className="news-note">{t("Summarizing…")}</p>
        ) : (
          <>
            <p className="news-sum-kind">{t(KIND_LABEL[res?.kind || "none"])}</p>
            {bullets ? (
              <ul>
                {lines.map((l, i) => (
                  <li key={i}>{l.replace(/^[-*•]\s+/, "")}</li>
                ))}
              </ul>
            ) : (
              lines.map((l, i) => <p key={i}>{l}</p>)
            )}
          </>
        )}
      </div>

      <h3 className="news-h3">{t("Related tickers")}</h3>
      <p className="news-sub-h">{t("On the map")}</p>
      <div className="news-rel">
        {companies.length ? (
          companies.map((id) => (
            <span key={id} className="news-co">
              <b>{ticker[id] || "—"}</b> {name(id)}
            </span>
          ))
        ) : (
          <span className="news-note">{loading ? "…" : t("None found.")}</span>
        )}
      </div>
      {others.length > 0 && (
        <>
          <p className="news-sub-h">{t("Other tickers")}</p>
          <div className="news-rel">
            {others.map((x) => (
              <span key={x} className="news-chip">
                {x}
              </span>
            ))}
          </div>
        </>
      )}
    </article>
  );
}
